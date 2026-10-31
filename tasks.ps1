<#
.SYNOPSIS
Automation script for Spotter Fuel Route Planner (Windows PowerShell).

.DESCRIPTION
Available targets:
  setup  - Create venv, install all dependencies, run migrations
  load   - Geocode and load fuel stations into database
  run    - Start local development server
  test   - Run full pytest test suite
  bench  - Run performance benchmark on 6 canonical city pairs
  lint   - Run ruff linter and formatter check
#>

[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [ValidateSet("setup", "load", "run", "test", "bench", "lint")]
    [string]$Target = "bench"
)

$ErrorActionPreference = "Stop"

$VenvPython = ".\.venv\Scripts\python.exe"
$VenvPip    = ".\.venv\Scripts\pip.exe"
$VenvPytest = ".\.venv\Scripts\pytest.exe"
$VenvRuff   = ".\.venv\Scripts\ruff.exe"

switch ($Target) {
    "setup" {
        Write-Host "Setting up Python virtual environment..." -ForegroundColor Cyan
        if (-not (Test-Path ".\.venv")) {
            py -3.12 -m venv .venv
        }
        & $VenvPip install --upgrade pip
        & $VenvPip install -r requirements.txt -r requirements-dev.txt
        & $VenvPython manage.py migrate
        Write-Host "Setup complete." -ForegroundColor Green
    }
    "load" {
        Write-Host "Loading fuel stations into database..." -ForegroundColor Cyan
        & $VenvPython manage.py load_stations
        Write-Host "Station load complete." -ForegroundColor Green
    }
    "run" {
        Write-Host "Starting development server at http://127.0.0.1:8000/map/ ..." -ForegroundColor Cyan
        & $VenvPython manage.py runserver 127.0.0.1:8000
    }
    "test" {
        Write-Host "Running pytest test suite..." -ForegroundColor Cyan
        & $VenvPytest -v
    }
    "bench" {
        Write-Host "Running route planning benchmark..." -ForegroundColor Cyan
        & $VenvPython manage.py benchmark_routes --mock
    }
    "lint" {
        Write-Host "Running ruff check and formatting check..." -ForegroundColor Cyan
        & $VenvRuff check .
        & $VenvRuff format --check .
    }
}
