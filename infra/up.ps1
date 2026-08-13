<#
.SYNOPSIS
  Brings the whole Phase 1 stack up from scratch, or resumes it if it's
  half-up. Safe to run repeatedly (every step checks "does this already
  exist" before acting) - that's what makes it safe to use as the daily
  "get everything running again" command instead of retyping the runbook.

.PARAMETER AutoApproveTerraform
  Skips the interactive y/n confirmation before `terraform apply`. Off by
  default on purpose: everything up to Terraform is pure infra bring-up
  (cluster/helm/kubectl), but applying Terraform changes what you decide
  to review, not just what you decide to run.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File infra\up.ps1
  powershell -ExecutionPolicy Bypass -File infra\up.ps1 -AutoApproveTerraform
#>

param(
    [switch]$AutoApproveTerraform
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptRoot

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "    OK: $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host "    WARN: $msg" -ForegroundColor Yellow
}

function Invoke-Checked {
    param([Parameter(Mandatory)][string]$Command)
    Write-Host "    running: $Command" -ForegroundColor DarkGray
    Invoke-Expression $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit $LASTEXITCODE): $Command"
    }
}

# ---------------------------------------------------------------------------
# 1. Kind cluster
# ---------------------------------------------------------------------------
Write-Step "Kind cluster (ai-builder)"
$existingClusters = & kind get clusters 2>$null
if ($existingClusters -contains "ai-builder") {
    Write-Ok "cluster already exists, skipping create"
}
else {
    Invoke-Checked "kind create cluster --config `"$ScriptRoot\kind\kind-config.yaml`""
}
Invoke-Checked "kubectl config use-context kind-ai-builder | Out-Null"

# ---------------------------------------------------------------------------
# 2. ingress-nginx
# ---------------------------------------------------------------------------
Write-Step "ingress-nginx"
Invoke-Checked "helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx 2>&1 | Out-Null"
Invoke-Checked "helm repo update ingress-nginx | Out-Null"

$ingressReleases = & helm list -n ingress-nginx -q 2>$null
if ($ingressReleases -contains "ingress-nginx") {
    Write-Ok "release already installed (values changes require a manual 'helm upgrade' - this script won't silently re-apply edited values)"
}
else {
    Invoke-Checked "helm install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace -f `"$ScriptRoot\ingress\ingress-nginx-values.yaml`""
}

Write-Host "    waiting for controller pod to be ready..."
Invoke-Checked "kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=180s"
Write-Ok "ingress-nginx controller ready"

# ---------------------------------------------------------------------------
# 3. LocalStack auth token -> Kubernetes Secret
#    Never written into values.yaml or Git. Resolution order:
#    env var -> local gitignored file -> interactive prompt (offers to save).
# ---------------------------------------------------------------------------
Write-Step "LocalStack auth token"
Invoke-Checked "kubectl create namespace localstack --dry-run=client -o yaml | kubectl apply -f - | Out-Null"

$secretExists = & kubectl get secret localstack-auth -n localstack --ignore-not-found -o name 2>$null
if ($secretExists) {
    Write-Ok "localstack-auth secret already exists in cluster, skipping"
}
else {
    $tokenFile = Join-Path $ScriptRoot "localstack\.auth-token"
    $token = $null

    if ($env:LOCALSTACK_AUTH_TOKEN) {
        $token = $env:LOCALSTACK_AUTH_TOKEN
        Write-Ok "using LOCALSTACK_AUTH_TOKEN from environment"
    }
    elseif (Test-Path $tokenFile) {
        $token = (Get-Content $tokenFile -Raw).Trim()
        Write-Ok "using token from infra/localstack/.auth-token (gitignored)"
    }
    else {
        Write-Warn "no token found in env var or local file"
        $secureToken = Read-Host -Prompt "Paste your LocalStack auth token (from app.localstack.cloud)" -AsSecureString
        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
        $token = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

        $save = Read-Host -Prompt "Save this token to infra/localstack/.auth-token for next time? (gitignored) [y/N]"
        if ($save -eq "y") {
            Set-Content -Path $tokenFile -Value $token -NoNewline
            Write-Ok "saved to $tokenFile"
        }
    }

    if (-not $token) {
        throw "No LocalStack auth token available - cannot proceed."
    }

    Invoke-Checked "kubectl create secret generic localstack-auth -n localstack --from-literal=LOCALSTACK_AUTH_TOKEN=`"$token`""
}

# ---------------------------------------------------------------------------
# 4. LocalStack itself - `upgrade --install` is idempotent regardless of
#    whether this is a fresh install or a re-run, so no existence check needed.
# ---------------------------------------------------------------------------
Write-Step "LocalStack"
Invoke-Checked "helm repo add localstack https://localstack.github.io/helm-charts 2>&1 | Out-Null"
Invoke-Checked "helm repo update localstack | Out-Null"
Invoke-Checked "helm upgrade --install localstack localstack/localstack -n localstack -f `"$ScriptRoot\localstack\values.yaml`""

Write-Host "    waiting for LocalStack pod to be ready (can take a while on first image pull)..."
Invoke-Checked "kubectl wait --namespace localstack --for=condition=ready pod --selector=app.kubernetes.io/name=localstack --timeout=300s"
Write-Ok "LocalStack ready"

# ---------------------------------------------------------------------------
# 5. Ingress manifests (idempotent - kubectl apply is a no-op if unchanged)
# ---------------------------------------------------------------------------
Write-Step "Ingress manifests"
Invoke-Checked "kubectl apply -f `"$ScriptRoot\ingress\manifests\localstack-ingress.yaml`""
Invoke-Checked "kubectl apply -f `"$ScriptRoot\ingress\manifests\app-ingress.yaml`""
Write-Ok "applied"

# ---------------------------------------------------------------------------
# 6. Hosts file sanity check (read-only - editing hosts needs admin rights,
#    left to you deliberately rather than a script silently elevating)
# ---------------------------------------------------------------------------
Write-Step "Hosts file check"
$hostsPath = "$env:WINDIR\System32\drivers\etc\hosts"
$hostsContent = Get-Content $hostsPath -ErrorAction SilentlyContinue
$missing = @()
foreach ($h in @("localstack.local", "app.local")) {
    if (-not ($hostsContent -match [regex]::Escape($h))) {
        $missing += $h
    }
}
if ($missing.Count -gt 0) {
    Write-Warn "missing from hosts file: $($missing -join ', ')"
    Write-Warn "add as Administrator: `"127.0.0.1 $($missing -join ' 127.0.0.1 ')`" to $hostsPath"
}
else {
    Write-Ok "hosts file entries present"
}

# ---------------------------------------------------------------------------
# 7. Reachability check
# ---------------------------------------------------------------------------
Write-Step "Reachability check"
$maxRetries = 10
$healthy = $false
for ($i = 0; $i -lt $maxRetries; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localstack.local/_localstack/health" -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    }
    catch { Start-Sleep -Seconds 3 }
}
if ($healthy) {
    Write-Ok "localstack.local reachable through ingress"
}
else {
    Write-Warn "could not reach http://localstack.local - check the hosts file entries above"
}

# ---------------------------------------------------------------------------
# 8. Terraform
# ---------------------------------------------------------------------------
Write-Step "Terraform"
Push-Location "$RepoRoot\infra\terraform"
try {
    Invoke-Checked "terraform init -input=false"
    Invoke-Checked "terraform plan -out=tfplan"

    if ($AutoApproveTerraform) {
        Invoke-Checked "terraform apply -auto-approve tfplan"
    }
    else {
        $confirm = Read-Host -Prompt "Apply the Terraform plan above? [y/N]"
        if ($confirm -eq "y") {
            Invoke-Checked "terraform apply tfplan"
        }
        else {
            Write-Warn "skipped terraform apply - infra may be out of sync with the plan above"
        }
    }

    Write-Host ""
    Write-Host "---- Terraform outputs ----" -ForegroundColor Cyan
    Invoke-Checked "terraform output"
}
finally {
    Remove-Item -Path "tfplan" -ErrorAction SilentlyContinue
    Pop-Location
}

Write-Host ""
Write-Host "==> Done." -ForegroundColor Cyan
