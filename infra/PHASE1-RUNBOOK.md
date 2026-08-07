# Phase 1 Runbook — commands to run yourself, in order

**Fast path**: once you've been through this manually and understand what
each step does, `infra\up.ps1` automates all of it (idempotent — safe to
run whether everything's down, half up, or already running):
```
powershell -ExecutionPolicy Bypass -File infra\up.ps1
```
It stops for confirmation before `terraform apply` by default; pass
`-AutoApproveTerraform` to skip that too. The steps below are the manual,
one-command-at-a-time version — useful the first time through, or for
debugging when the script hits something unexpected.

All commands below are written for `cmd.exe` (single-line, `set VAR=value`
for environment variables) since that's the shell in use. If you switch to
PowerShell later, swap `set X=Y` for `$env:X = "Y"`.

## 0. Hosts file entries

Add these to `C:\Windows\System32\drivers\etc\hosts` (as Administrator):
```
127.0.0.1 localstack.local
127.0.0.1 test.local
```
Why: Kind maps host ports 80/443 -> the control-plane node -> ingress-nginx.
Ingress routes by the `Host` header, so your browser/curl/Terraform need a
real hostname to send — `localhost` alone can't carry that routing info.

## 1. Create the Kind cluster — DONE

## 2. Install ingress-nginx
```
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
helm install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace -f infra/ingress/ingress-nginx-values.yaml
```
Wait for it to be ready:
```
kubectl get pods -n ingress-nginx -w
```
(Ctrl+C once the controller pod is `Running` and `1/1 Ready`.)

## 3. Install LocalStack

**Known issue you'll hit**: the pod will crash-loop with exit code 55 and
a log saying "License activation failed". This isn't a mistake in the
config — LocalStack changed its licensing in March 2026 so that *every*
install (even free/non-commercial use) now requires a registered account
and an auth token. The community/pro images were merged. Individuals can
still use it free — you just need the token.

### 3a. Get a free auth token
1. Create a free account at https://app.localstack.cloud
2. Find your auth token in the account dashboard (Account → Auth Token,
   or similar — the UI may have moved by the time you read this).

### 3b. Store it as a Kubernetes Secret (not in any file we commit)
```
kubectl create namespace localstack
kubectl create secret generic localstack-auth -n localstack --from-literal=LOCALSTACK_AUTH_TOKEN=<paste your token here>
```
This is the same lesson from the K8s ConfigMaps/Secrets module: the token
is a secret, so it's created directly against the cluster, never written
into `values.yaml` or committed to Git. `infra/localstack/values.yaml`
already references this Secret by name via `envFrom`.

### 3c. Install (or re-install if you already tried once)
If your earlier attempt is still crash-looping, remove it first:
```
helm uninstall localstack -n localstack
```
Then install:
```
helm install localstack localstack/localstack -n localstack -f infra/localstack/values.yaml
```
(Namespace already exists from step 3b, so no `--create-namespace` needed
this time — using it again is harmless, but the flag is unnecessary.)

### 3d. Verify
Confirm the image (should be `localstack/localstack:latest`):
```
kubectl get pod -n localstack -o jsonpath="{.items[0].spec.containers[0].image}"
```
Watch it come up:
```
kubectl get pods -n localstack -w
```
(Ctrl+C once `1/1 Running`.) If it's still failing, check logs:
```
kubectl logs -n localstack -l app.kubernetes.io/name=localstack --tail=100
```

## 4. Apply the Ingress manifests
```
kubectl apply -f infra/ingress/manifests/localstack-ingress.yaml
kubectl apply -f infra/ingress/manifests/test-app.yaml
```

## 5. Verify the ingress chain end-to-end
```
curl http://test.local/
```
You should see the nginxdemos "hello" page (shows request/pod info) —
this proves: host -> Kind port mapping -> ingress-nginx -> Service -> pod.

```
curl http://localstack.local/_localstack/health
```
Should return JSON showing `s3`, `iam`, `sts`, `kms`, `route53` as
`available` — proves LocalStack is reachable the same way Terraform will
reach it.

## 6. Terraform
```
cd infra/terraform
terraform init
terraform plan
terraform apply
```
Read the plan output before typing `yes` — this is the actual point of
running it yourself: see what Terraform intends to create and why, before
it happens.

## 6b. Enable IAM enforcement (required — off by default)

LocalStack does not enforce IAM policies unless explicitly told to —
without this, every API call succeeds regardless of attached policies,
which makes the whole point of step 7 silently meaningless. Apply the
updated values (adds `ENFORCE_IAM=1`):
```
helm upgrade localstack localstack/localstack -n localstack -f infra/localstack/values.yaml
kubectl get pods -n localstack -w
```
(Ctrl+C once the new pod is `1/1 Running` — this restarts LocalStack, so
give it a few seconds after that before retrying step 7. Since PERSISTENCE
is enabled, your Terraform-created buckets/roles/keys survive the restart.)

## 7. Prove least-privilege actually works

Get the outputs (the two secrets are hidden by default):
```
terraform output orchestrator_role_arn
terraform output -raw orchestrator_app_access_key_id
terraform output -raw orchestrator_app_secret_access_key
```

Use the orchestrator-app user's own keys to assume the role via STS:
```
set AWS_ACCESS_KEY_ID=<paste orchestrator_app_access_key_id>
set AWS_SECRET_ACCESS_KEY=<paste orchestrator_app_secret_access_key>

aws sts assume-role --endpoint-url http://localstack.local --role-arn "<paste orchestrator_role_arn>" --role-session-name test-session
```
Copy the `AccessKeyId`, `SecretAccessKey`, and `SessionToken` from the
response into new env vars (`AWS_SESSION_TOKEN` too this time):
```
set AWS_ACCESS_KEY_ID=<AccessKeyId from response>
set AWS_SECRET_ACCESS_KEY=<SecretAccessKey from response>
set AWS_SESSION_TOKEN=<SessionToken from response>
```

Then:
```
aws --endpoint-url http://localstack.local s3 ls s3://demo-allowed-bucket
```
Should succeed — this bucket is in the policy.
```
aws --endpoint-url http://localstack.local s3 ls s3://demo-denied-bucket
```
Should fail with `AccessDenied` — this bucket is NOT in the policy.

If the second command fails with `AccessDenied`, least-privilege is
actually working — that failure is the success condition for this exercise.

**Known issue (confirmed, not our config)**: as of the LocalStack version
in use here, `ENFORCE_IAM=1` does not actually block anything — verified
by testing `iam:list-users` (an action granted to no one) succeeding
under the assumed role. Matches an open upstream bug:
https://github.com/localstack/localstack/issues/7183
The Terraform-defined policy itself (`main.tf`) is correctly scoped —
this is a LocalStack enforcement-engine gap, not a flaw in the IAM design.
Treat the policy code as the deliverable for this exercise; local runtime
enforcement isn't currently trustworthy as a verification step. Revisit
if/when the upstream issue is resolved.

**Sanity check (optional but worth doing)**: set your env vars back to the
`orchestrator_app` user's own static keys (not the assumed-role temp
creds) and try `s3 ls` on `demo-allowed-bucket`. This should now also fail
with `AccessDenied` — the user itself has no policy attached, only the
role it can assume does. If this succeeds, IAM enforcement isn't actually
on and something's still wrong.

## Cleanup (when you want to tear it down)
```
cd infra/terraform
terraform destroy
kind delete cluster --name ai-builder
```
