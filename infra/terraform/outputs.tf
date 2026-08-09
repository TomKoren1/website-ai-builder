output "orchestrator_role_arn" {
  value       = aws_iam_role.orchestrator.arn
  description = "Role to assume via STS to prove least-privilege access"
}

output "demo_allowed_bucket" {
  value = aws_s3_bucket.demo_allowed.bucket
}

output "demo_denied_bucket" {
  value = aws_s3_bucket.demo_denied.bucket
}

output "kms_key_arn" {
  value = aws_kms_key.orchestrator.arn
}

output "orchestrator_app_access_key_id" {
  value     = aws_iam_access_key.orchestrator_app.id
  sensitive = true
}

output "orchestrator_app_secret_access_key" {
  value     = aws_iam_access_key.orchestrator_app.secret
  sensitive = true
}

output "ci_deploy_role_arn" {
  value       = aws_iam_role.ci_deploy.arn
  description = "Role Gitea Actions assumes via STS to sync site files to S3"
}

output "ci_deploy_app_access_key_id" {
  value     = aws_iam_access_key.ci_deploy_app.id
  sensitive = true
}

output "ci_deploy_app_secret_access_key" {
  value     = aws_iam_access_key.ci_deploy_app.secret
  sensitive = true
}

output "reverse_proxy_role_arn" {
  value       = aws_iam_role.reverse_proxy.arn
  description = "Role the reverse-proxy service assumes via STS to read site files from S3"
}

output "reverse_proxy_app_access_key_id" {
  value     = aws_iam_access_key.reverse_proxy_app.id
  sensitive = true
}

output "reverse_proxy_app_secret_access_key" {
  value     = aws_iam_access_key.reverse_proxy_app.secret
  sensitive = true
}
