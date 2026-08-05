# Creates the Render web service with env vars pulled from apps/api/.env.
# Usage: ./scripts/create-render-service.ps1
param(
  [string]$Repo = "https://github.com/AmitxParmar/agentic-knowledge-base"
)

$envPath = Resolve-Path "apps/api/.env"
$envMap = @{}

Get-Content $envPath | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith("#")) { return }
  if ($line -match "^([^=]+)=(.*)$") {
    $k = $Matches[1].Trim()
    $v = $Matches[2].Trim()
    # Strip surrounding quotes
    if ($v.StartsWith('"') -and $v.EndsWith('"')) { $v = $v.Substring(1, $v.Length - 2) }
    if ($v.StartsWith("'") -and $v.EndsWith("'")) { $v = $v.Substring(1, $v.Length - 2) }
    $envMap[$k] = $v
  }
}

$required = @(
  "APP_ENV",
  "CORS_ORIGINS",
  "DATABASE_URL",
  "REDIS_URL",
  "MODEL_GATEWAY_PROVIDER",
  "MODEL_GATEWAY_MODEL",
  "MODEL_GATEWAY_GROQ_API_KEY",
  "COHERE_API_KEY",
  "COHERE_EMBED_MODEL",
  "COHERE_RERANK_MODEL",
  "R2_ENDPOINT",
  "R2_ACCESS_KEY_ID",
  "R2_SECRET_ACCESS_KEY",
  "R2_BUCKET",
  "LOGFIRE_TOKEN"
)

$envArgs = @()
foreach ($key in $required) {
  if ($envMap.ContainsKey($key) -and $envMap[$key]) {
    $envArgs += "--env-var"
    $envArgs += "$key=$($envMap[$key])"
  } else {
    Write-Warning "$key is missing from .env — setting placeholder"
    $envArgs += "--env-var"
    $envArgs += "$key=REPLACE_ME"
  }
}

# Fallbacks for non-secret defaults if .env lacks them
if (-not $envMap.ContainsKey("APP_ENV") -or -not $envMap["APP_ENV"]) { $envArgs += "--env-var"; $envArgs += "APP_ENV=production" }
if (-not $envMap.ContainsKey("MODEL_GATEWAY_PROVIDER") -or -not $envMap["MODEL_GATEWAY_PROVIDER"]) { $envArgs += "--env-var"; $envArgs += "MODEL_GATEWAY_PROVIDER=groq" }
if (-not $envMap.ContainsKey("MODEL_GATEWAY_MODEL") -or -not $envMap["MODEL_GATEWAY_MODEL"]) { $envArgs += "--env-var"; $envArgs += "MODEL_GATEWAY_MODEL=llama-3.3-70b-versatile" }
if (-not $envMap.ContainsKey("COHERE_EMBED_MODEL") -or -not $envMap["COHERE_EMBED_MODEL"]) { $envArgs += "--env-var"; $envArgs += "COHERE_EMBED_MODEL=embed-english-v3.0" }
if (-not $envMap.ContainsKey("COHERE_RERANK_MODEL") -or -not $envMap["COHERE_RERANK_MODEL"]) { $envArgs += "--env-var"; $envArgs += "COHERE_RERANK_MODEL=rerank-english-v3.0" }

Write-Host "Creating Render service with $($envArgs.Count / 2) env vars..."

$createArgs = @(
  "services",
  "create",
  "--name", "agentic-research-api",
  "--type", "web_service",
  "--repo", $Repo,
  "--runtime", "docker",
  "--root-directory", "apps/api",
  "--branch", "main",
  "--plan", "free",
  "--health-check-path", "/health",
  "--output", "json",
  "--confirm"
) + $envArgs

& render $createArgs 2>&1
