# ---------------------------------------------------------------------------
# S3 fixtures — not real customer buckets. They exist purely so the IAM
# policy below has something concrete to allow/deny against.
# "allowed" = the role should be able to touch it. "denied" = it shouldn't,
# and proving that failure is the actual point of the exercise.
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "demo_allowed" {
  bucket = "demo-allowed-bucket"
}

resource "aws_s3_bucket" "demo_denied" {
  bucket = "demo-denied-bucket"
}

# ---------------------------------------------------------------------------
# KMS key — this becomes the real Customer Master Key later, used to wrap
# the per-user Data Encryption Keys that protect friends' LLM API keys
# (see the "API Key Security" section in overview.md). Created now so the
# IAM policy has a real key ARN to scope kms:Decrypt to, instead of "*".
# ---------------------------------------------------------------------------
resource "aws_kms_key" "orchestrator" {
  description             = "AI Builder orchestrator CMK - wraps DEKs for user-supplied LLM API keys"
  deletion_window_in_days = 7
}

resource "aws_kms_alias" "orchestrator" {
  name          = "alias/ai-builder-orchestrator"
  target_key_id = aws_kms_key.orchestrator.key_id
}

# ---------------------------------------------------------------------------
# The identity representing "the orchestrator backend pod". In a real EKS
# deployment this would be an IRSA-bound role instead of a static IAM user
# with access keys — we're using a user here only because LocalStack in a
# local Kind cluster has no OIDC provider to bind IRSA to. The point being
# practiced (a narrowly-scoped role, assumed via STS, rather than handing
# out static creds with broad permissions) is the same either way.
# ---------------------------------------------------------------------------
resource "aws_iam_user" "orchestrator_app" {
  name = "orchestrator-app"
}

resource "aws_iam_access_key" "orchestrator_app" {
  user = aws_iam_user.orchestrator_app.name
}

# Trust policy: only the orchestrator-app user may assume this role.
# This is the boundary that matters — without it, *any* authenticated
# caller could assume a role with S3 + KMS access.
data "aws_iam_policy_document" "orchestrator_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = [aws_iam_user.orchestrator_app.arn]
    }
  }
}

resource "aws_iam_role" "orchestrator" {
  name               = "orchestrator-role"
  assume_role_policy = data.aws_iam_policy_document.orchestrator_trust.json
}

# The actual least-privilege grant: only the allowed bucket, only the
# actions the orchestrator genuinely needs, only this one KMS key,
# only the decrypt action (never kms:Encrypt/kms:CreateKey/etc — the
# orchestrator consumes secrets, it doesn't mint or manage keys).
data "aws_iam_policy_document" "orchestrator_permissions" {
  statement {
    sid    = "S3AllowedBucketOnly"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.demo_allowed.arn,
      "${aws_s3_bucket.demo_allowed.arn}/*",
    ]
  }

  statement {
    sid       = "KMSDecryptOnly"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.orchestrator.arn]
  }
}

resource "aws_iam_policy" "orchestrator_permissions" {
  name   = "orchestrator-least-privilege"
  policy = data.aws_iam_policy_document.orchestrator_permissions.json
}

resource "aws_iam_role_policy_attachment" "orchestrator" {
  role       = aws_iam_role.orchestrator.name
  policy_arn = aws_iam_policy.orchestrator_permissions.arn
}
