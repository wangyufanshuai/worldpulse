param(
    [ValidateSet("up", "down", "ps", "logs")]
    [string]$Action = "up"
)

$env:WORLDPULSE_API_PORT = "8011"
$files = @(
    "-f", "docker-compose.yml",
    "-f", "docker-compose.postgres.yml",
    "-f", "docker-compose.v112-test.yml"
)

if ($Action -eq "up") {
    docker compose -p worldpulse-v112-test @files up -d --build
} elseif ($Action -eq "down") {
    docker compose -p worldpulse-v112-test @files down -v
} elseif ($Action -eq "logs") {
    docker compose -p worldpulse-v112-test @files logs --tail 200
} else {
    docker compose -p worldpulse-v112-test @files ps
}
