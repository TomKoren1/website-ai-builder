# Points the AWS provider at LocalStack instead of real AWS.
#
# access_key/secret_key are dummy values — LocalStack (community edition)
# doesn't validate credentials, it just needs *something* present so the
# AWS SDK doesn't refuse to build a request.
#
# endpoints are all set to the same URL because LocalStack multiplexes
# every service behind its single edge port (4566), which we've exposed
# through ingress-nginx at localstack.local (see infra/ingress/manifests).
provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  # Path-style S3 addressing (http://host/bucket/key instead of
  # http://bucket.host/key). Virtual-hosted-style would need our Ingress
  # to route arbitrary *.localstack.local subdomains, which it doesn't —
  # that's a deliberately separate problem from the domain->bucket routing
  # trick we're using for real customer sites later.
  s3_use_path_style = true

  endpoints {
    s3      = "http://localstack.local"
    iam     = "http://localstack.local"
    sts     = "http://localstack.local"
    kms     = "http://localstack.local"
    route53 = "http://localstack.local"
  }
}
