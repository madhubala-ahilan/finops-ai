param(
  [string]$TerraformDir = "D:\finops-ai\terraform",
  [string]$ProjectRoot = "D:\finops-ai",
  [string]$BackendTag = "",
  [string]$FrontendTag = "",
  [switch]$ApplyAfterPush
)

$ErrorActionPreference = "Stop"

if (-not $BackendTag -and -not $FrontendTag) {
  $tag = "v" + (Get-Date -Format "yyyyMMddHHmmss")
  $BackendTag = $tag
  $FrontendTag = $tag
}
elseif (-not $BackendTag) {
  $BackendTag = $FrontendTag
}
elseif (-not $FrontendTag) {
  $FrontendTag = $BackendTag
}

Push-Location $TerraformDir
try {
  $acr = terraform output -raw acr_login_server
  if (-not $acr) {
    throw "Terraform output acr_login_server is empty. Create ACR first with the target apply from TERRAFORM_STEP_BY_STEP.md."
  }

  $acrName = $acr.Split(".")[0]
  $dockerAvailable = $false
  try {
    docker info *> $null
    $dockerAvailable = $LASTEXITCODE -eq 0
  }
  catch {
    $dockerAvailable = $false
  }

  if ($dockerAvailable) {
    Write-Host "Logging in to ACR: $acrName"
    az acr login --name $acrName
  }
  else {
    Write-Host "Docker Desktop is not available. Using Azure Container Registry cloud builds."
  }

  Push-Location $ProjectRoot
  try {
    $backendImage = "$acr/finopsai-backend:$BackendTag"
    $frontendImage = "$acr/finopsai-frontend:$FrontendTag"

    if ($dockerAvailable) {
      Write-Host "Building backend: $backendImage"
      docker build --no-cache --build-arg BUILD_VERSION=$BackendTag -t $backendImage ./backend
      docker push $backendImage

      Write-Host "Building frontend: $frontendImage"
      docker build --no-cache --build-arg BUILD_VERSION=$FrontendTag -t $frontendImage ./frontend
      docker push $frontendImage
    }
    else {
      Write-Host "ACR cloud build backend: finopsai-backend:$BackendTag"
      az acr build --registry $acrName --image "finopsai-backend:$BackendTag" --build-arg "BUILD_VERSION=$BackendTag" ./backend
      if ($LASTEXITCODE -ne 0) {
        throw "ACR cloud build failed for backend image tag $BackendTag. Terraform was not applied."
      }

      Write-Host "ACR cloud build frontend: finopsai-frontend:$FrontendTag"
      az acr build --registry $acrName --image "finopsai-frontend:$FrontendTag" --build-arg "BUILD_VERSION=$FrontendTag" ./frontend
      if ($LASTEXITCODE -ne 0) {
        throw "ACR cloud build failed for frontend image tag $FrontendTag. Terraform was not applied."
      }
    }
  }
  finally {
    Pop-Location
  }

  if ($ApplyAfterPush) {
    Write-Host "Applying Terraform with pushed image tags..."
    terraform apply `
      -var "backend_image_tag=$BackendTag" `
      -var "frontend_image_tag=$FrontendTag" `
      -auto-approve
  }
  else {
    Write-Host "Images pushed. Next run:"
    Write-Host "  cd $TerraformDir"
    Write-Host "  terraform apply -var `"backend_image_tag=$BackendTag`" -var `"frontend_image_tag=$FrontendTag`""
  }
}
finally {
  Pop-Location
}
