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

  # Bucket creation for user sites (Flow B — see docs/errors.md and
  # overview.md's reverse-proxy correction). Scoped to the "site-*" name
  # prefix, never "*": bucket names are always generated server-side as
  # "site-{project_id}" (backend/app/routers/domains.py), never taken from
  # user input, so this prefix is the only namespace the orchestrator can
  # ever touch — it can't be tricked into creating/listing a bucket outside
  # it. Deliberately NO PutObject/GetObject here: the orchestrator only
  # ever creates the bucket (at domain-registration time); writing site
  # files is ci-deploy-role's job, reading them back is reverse-proxy-role's
  # — see those below. Splitting by who-does-what, not sharing one broad
  # role, is the actual point of this exercise.
  statement {
    sid    = "S3SiteBucketCreateOnly"
    effect = "Allow"
    actions = [
      "s3:CreateBucket",
      "s3:ListBucket",
    ]
    resources = [
      "arn:aws:s3:::site-*",
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

# ---------------------------------------------------------------------------
# ci-deploy-role — assumed by the Gitea Actions CI job (via act_runner,
# using its own static keys the same way orchestrator-app does; there's no
# OIDC/IRSA available under Kind+LocalStack to do this without static keys
# either). Only what `aws s3 sync` actually needs: write and delete objects,
# list to diff against what's already there. No CreateBucket (the
# orchestrator already created it before CI ever runs) and no GetObject
# (CI never needs to read a file back, only push new ones) — a leaked
# ci-deploy credential can deface a site's content but can't read it back
# or spin up new buckets.
# ---------------------------------------------------------------------------
resource "aws_iam_user" "ci_deploy_app" {
  name = "ci-deploy-app"
}

resource "aws_iam_access_key" "ci_deploy_app" {
  user = aws_iam_user.ci_deploy_app.name
}

data "aws_iam_policy_document" "ci_deploy_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [aws_iam_user.ci_deploy_app.arn]
    }
  }
}

resource "aws_iam_role" "ci_deploy" {
  name               = "ci-deploy-role"
  assume_role_policy = data.aws_iam_policy_document.ci_deploy_trust.json
}

data "aws_iam_policy_document" "ci_deploy_permissions" {
  statement {
    sid    = "S3SiteBucketWriteOnly"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
    ]
    resources = [
      "arn:aws:s3:::site-*",
      "arn:aws:s3:::site-*/*",
    ]
  }
}

resource "aws_iam_policy" "ci_deploy_permissions" {
  name   = "ci-deploy-least-privilege"
  policy = data.aws_iam_policy_document.ci_deploy_permissions.json
}

resource "aws_iam_role_policy_attachment" "ci_deploy" {
  role       = aws_iam_role.ci_deploy.name
  policy_arn = aws_iam_policy.ci_deploy_permissions.arn
}

# ---------------------------------------------------------------------------
# reverse-proxy-role — assumed by the reverse-proxy service that actually
# serves site content to visitors (see overview.md correction #1). Read
# only: it looks up domain -> bucket in Postgres, then GETs the object.
# Never needs to create, write, or delete anything.
# ---------------------------------------------------------------------------
resource "aws_iam_user" "reverse_proxy_app" {
  name = "reverse-proxy-app"
}

resource "aws_iam_access_key" "reverse_proxy_app" {
  user = aws_iam_user.reverse_proxy_app.name
}

data "aws_iam_policy_document" "reverse_proxy_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [aws_iam_user.reverse_proxy_app.arn]
    }
  }
}

resource "aws_iam_role" "reverse_proxy" {
  name               = "reverse-proxy-role"
  assume_role_policy = data.aws_iam_policy_document.reverse_proxy_trust.json
}

data "aws_iam_policy_document" "reverse_proxy_permissions" {
  statement {
    sid    = "S3SiteBucketReadOnly"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      "arn:aws:s3:::site-*",
      "arn:aws:s3:::site-*/*",
    ]
  }
}

resource "aws_iam_policy" "reverse_proxy_permissions" {
  name   = "reverse-proxy-least-privilege"
  policy = data.aws_iam_policy_document.reverse_proxy_permissions.json
}

resource "aws_iam_role_policy_attachment" "reverse_proxy" {
  role       = aws_iam_role.reverse_proxy.name
  policy_arn = aws_iam_policy.reverse_proxy_permissions.arn
}
