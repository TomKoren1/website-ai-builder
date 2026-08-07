terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Local state for now — simplest option while this is a single learner
  # working alone. Revisit with a remote backend (even an S3-in-LocalStack
  # bucket) once state locking / team access actually matters.
  backend "local" {
    path = "terraform.tfstate"
  }
}
