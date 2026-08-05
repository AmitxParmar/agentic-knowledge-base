# PowerShell — reads .env and sets only the listed keys on the Render service. Never prints values.
param(
  [string]$ServiceId = "srv-d9p5a8rm8hqs73abnhs0"
)

$envPath = Resolve-Path "apps/api/.env"
$keys = @(
  "DATABASE_URL", "REDIS_URL",
  "MODEL_GATEWAY_PROVIDER", "MODEL_GATEWAY_MODEL",
  "MODEL_GATEWAY_GROQ_API_KEY", "MODEL_GATEWAY_OPENROUTER_API_KEY", "MODEL_GATEWAY_OPENROUTER_MODEL",
  "COHERE_API_KEY", "COHERE_EMBED_MODEL", "COHERE_RERANK_MODEL",
  "R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET",
  "LOGFIRE_TOKEN", "CORS_ORIGINS", "APP_ENV"
)

$argsList = @("--confirm")
$lines = Get-Content $envPath
foreach ($line in $lines) {
  if (-not $line -or $line -match "^\s*#") { continue }
  foreach ($key in $keys) {
    if ($line -match "^\s*$key\s*=\s*(.*)$") {
      $value = $Matches[1].Trim()
      # strip surrounding quotes if present
      if ($value.StartsWith('"') -and $value.EndsWith('"')) { $value = $value.Substring(1, $value.Length - 2) }
      if ($value.StartsWith("'") -and $value.EndsWith("'")) { $value = $value.Substring(1, $value.Length - 2) }
      if ($value) {
        $argsList += "--env-var"
        $argsList += "$key=$value"
      }
    }
  }
}

# Force APP_ENV if absent
if (-not ($argsList -contains "-e" -or $argsList | Where-Object { $_ -like "APP_ENV=*" })) {
  $argsList += "--env-var"
  $argsList += "APP_ENV=production"
}

# Set safe defaults for non-secret keys not in .env
foreach ($kv in @(
  "MODEL_GATEWAY_PROVIDER=groq",
  "MODEL_GATEWAY_MODEL=llama-3.3-70b-versatile",
  "COHERE_EMBED_MODEL=embed-english-v3.0",
  "COHERE_RERANK_MODEL=rerank-english-v3.0"
)) {
  $k = $kv.Split("=")[0]
  if (-not ($argsList | Where-Object { $_ -like "$k=*" })) {
    $argsList += "--env-var"; $argsList += $kv
  }
}

Write-Host "Setting $($argsList.Count / 2) env vars on $ServiceId (values hidden)..."
& render services update $ServiceId $argsList 2>&1 | Select-Object -Last 20
