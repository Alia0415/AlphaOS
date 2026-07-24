param(
    [string]$RepoPath = ".",
    [string]$PythonPath = "",
    [string]$VenvPath = ".venv",
    [ValidateRange(1024, 65535)][int]$Port = 8000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$script:CurrentStage = "initialization"
$script:SecretValues = @()
$script:ArtifactDirectory = $null
$script:UvicornProcess = $null
$script:UvicornServerProcessId = $null
$script:UvicornStdout = $null
$script:UvicornStderr = $null
$script:Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Protect-Secrets {
    param([AllowNull()][string]$Text)

    if ($null -eq $Text) {
        return ""
    }
    $protected = $Text
    foreach ($secret in $script:SecretValues) {
        if (-not [string]::IsNullOrEmpty($secret)) {
            $protected = $protected.Replace($secret, "[REDACTED]")
        }
    }
    return $protected
}

function Write-Utf8Text {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [AllowNull()][string]$Text
    )

    [System.IO.File]::WriteAllText(
        $Path,
        (Protect-Secrets $Text),
        $script:Utf8NoBom
    )
}

function Write-JsonArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Value
    )

    $json = $Value | ConvertTo-Json -Depth 100
    Write-Utf8Text -Path (Join-Path $script:ArtifactDirectory $Name) -Text $json
}

function Get-ConfiguredValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$EnvFile
    )

    $processValue = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($processValue)) {
        return $processValue
    }

    $pattern = "^\s*(?:export\s+)?" + [regex]::Escape($Name) + "\s*=\s*(.*)$"
    foreach ($line in [System.IO.File]::ReadAllLines($EnvFile)) {
        if ($line -notmatch $pattern) {
            continue
        }
        $value = $Matches[1].Trim()
        if ($value.Length -ge 2) {
            $first = $value.Substring(0, 1)
            $last = $value.Substring($value.Length - 1, 1)
            if (($first -eq '"' -and $last -eq '"') -or
                ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        return $value
    }
    return $null
}

function Test-ConfiguredValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowNull()][string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }
    $normalized = $Value.Trim().ToLowerInvariant()
    $knownPlaceholders = @(
        "your_token_here",
        "your-api-key",
        "your_api_key",
        "your-pandaai-password",
        "your_password_here"
    )
    return $knownPlaceholders -notcontains $normalized
}

function Assert-Condition {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Get-PythonMinorVersion {
    param([Parameter(Mandatory = $true)][string]$Executable)

    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return $null
    }
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $versionOutput = @(
            & $Executable -c `
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" `
                2>&1
        )
        $versionExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($versionExitCode -ne 0 -or $versionOutput.Count -eq 0) {
        return $null
    }
    return ([string]$versionOutput[-1]).Trim()
}

function Test-CompatiblePythonVersion {
    param([AllowNull()][string]$Version)

    if ($Version -notmatch "^(\d+)\.(\d+)$") {
        return $false
    }
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    # panda_data 0.0.12 requires NumPy 1.26.4, whose Windows wheels support
    # CPython through 3.12. pytest 9 requires Python 3.10 or newer.
    return $major -eq 3 -and $minor -ge 10 -and $minor -le 12
}

function Find-CompatiblePython {
    param([AllowNull()][string]$RequestedPath)

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        try {
            $candidates += (Resolve-Path -LiteralPath $RequestedPath).Path
        }
        catch {
            throw "PythonPath does not exist."
        }
    }
    else {
        foreach ($commandName in @("python3.12", "python3.11", "python3.10", "python")) {
            $command = Get-Command $commandName -ErrorAction SilentlyContinue
            if ($null -ne $command -and $command.Source) {
                $candidates += $command.Source
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
            $localPrograms = Join-Path $env:USERPROFILE "AppData\Local\Programs\Python"
            foreach ($minor in @("312", "311", "310")) {
                $candidates += Join-Path $localPrograms "Python$minor\python.exe"
            }
            $runtimePattern = Join-Path `
                $env:USERPROFILE `
                ".cache\codex-runtimes\*\dependencies\python\python.exe"
            $candidates += @(
                Get-ChildItem -Path $runtimePattern -File -ErrorAction SilentlyContinue |
                    Select-Object -ExpandProperty FullName
            )
        }
    }

    foreach ($candidate in @($candidates | Select-Object -Unique)) {
        $version = Get-PythonMinorVersion -Executable $candidate
        if (Test-CompatiblePythonVersion -Version $version) {
            return [string]$candidate
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        throw "PythonPath must point to CPython 3.10, 3.11, or 3.12."
    }
    throw (
        "No compatible Python found. Install CPython 3.10-3.12 or pass " +
        "-PythonPath with a compatible python.exe."
    )
}

function Invoke-LoggedNative {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$LogName
    )

    $script:CurrentStage = $Stage
    Write-Host "==> $Stage"
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $rawOutput = @(& $FilePath @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $cleanOutput = @(
        $rawOutput | ForEach-Object {
            Protect-Secrets ([string]$_)
        }
    )
    $logPath = Join-Path $script:ArtifactDirectory $LogName
    [System.IO.File]::WriteAllLines(
        $logPath,
        [string[]]$cleanOutput,
        $script:Utf8NoBom
    )
    foreach ($line in $cleanOutput) {
        Write-Host $line
    }
    if ($exitCode -ne 0) {
        throw "$Stage failed with exit code $exitCode."
    }
}

function Invoke-ApiJson {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$ArtifactName,
        [AllowNull()]$Body = $null,
        [int]$TimeoutSec = 300
    )

    $script:CurrentStage = $Stage
    Write-Host "==> $Stage"
    $parameters = @{
        Uri = $Uri
        Method = $Method
        UseBasicParsing = $true
        TimeoutSec = $TimeoutSec
    }
    if ($Method -eq "POST") {
        $requestJson = $Body | ConvertTo-Json -Depth 100 -Compress
        $parameters["ContentType"] = "application/json; charset=utf-8"
        $parameters["Body"] = [System.Text.Encoding]::UTF8.GetBytes($requestJson)
    }

    try {
        $response = Invoke-WebRequest @parameters
    }
    catch {
        throw (Protect-Secrets $_.Exception.Message)
    }

    Assert-Condition ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) `
        "$Stage returned HTTP $($response.StatusCode)."
    $content = Protect-Secrets ([string]$response.Content)
    Write-Utf8Text `
        -Path (Join-Path $script:ArtifactDirectory $ArtifactName) `
        -Text $content
    try {
        return $content | ConvertFrom-Json
    }
    catch {
        throw "$Stage did not return valid JSON."
    }
}

function Sanitize-File {
    param([AllowNull()][string]$Path)

    if ($Path -and (Test-Path -LiteralPath $Path -PathType Leaf)) {
        $content = [System.IO.File]::ReadAllText($Path)
        Write-Utf8Text -Path $Path -Text $content
    }
}

function Test-IsDescendantProcess {
    param(
        [Parameter(Mandatory = $true)][int]$ChildProcessId,
        [Parameter(Mandatory = $true)][int]$AncestorProcessId
    )

    $currentProcessId = $ChildProcessId
    for ($depth = 0; $depth -lt 16 -and $currentProcessId -gt 0; $depth++) {
        if ($currentProcessId -eq $AncestorProcessId) {
            return $true
        }
        $processInfo = Get-CimInstance `
            -ClassName Win32_Process `
            -Filter "ProcessId = $currentProcessId" `
            -ErrorAction SilentlyContinue
        if ($null -eq $processInfo) {
            return $false
        }
        $currentProcessId = [int]$processInfo.ParentProcessId
    }
    return $false
}

function Stop-TrackedProcess {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    try {
        $process = [System.Diagnostics.Process]::GetProcessById($ProcessId)
    }
    catch [System.ArgumentException] {
        return
    }
    if ($process.HasExited) {
        return
    }
    $process.Kill()
    Assert-Condition ($process.WaitForExit(10000)) `
        "Process $ProcessId did not exit during cleanup."
}

$exitCode = 0
$failure = $null

try {
    $script:CurrentStage = "validate AlphaOS repository root"
    $resolvedRepo = (Resolve-Path -LiteralPath $RepoPath).Path
    $requiredMarkers = @(
        "AGENTS.md",
        "requirements.txt",
        "backend\main.py",
        "backend\agents\manager_agent.py",
        "tests"
    )
    foreach ($marker in $requiredMarkers) {
        Assert-Condition `
            (Test-Path -LiteralPath (Join-Path $resolvedRepo $marker)) `
            "RepoPath is not an AlphaOS repository root; missing $marker."
    }
    Set-Location -LiteralPath $resolvedRepo
    Write-Host "==> AlphaOS repository root validated"

    $script:CurrentStage = "validate .env"
    $envFile = Join-Path $resolvedRepo ".env"
    Assert-Condition (Test-Path -LiteralPath $envFile -PathType Leaf) `
        "The AlphaOS repository root does not contain .env."
    Write-Host "==> .env exists"

    $script:CurrentStage = "validate real credential configuration"
    $credentialNames = @(
        "ARK_API_KEY",
        "PANDADATA_USERNAME",
        "PANDADATA_PASSWORD"
    )
    $missingCredentials = @()
    foreach ($name in $credentialNames) {
        $value = Get-ConfiguredValue -Name $name -EnvFile $envFile
        if (-not (Test-ConfiguredValue -Name $name -Value $value)) {
            $missingCredentials += $name
        }
        else {
            $script:SecretValues += $value
        }
    }
    Assert-Condition ($missingCredentials.Count -eq 0) `
        ("Missing or placeholder credentials: " + ($missingCredentials -join ", "))
    Write-Host "==> Required credentials are configured (values not displayed)"

    $runId = Get-Date -Format "yyyyMMdd-HHmmss"
    $script:ArtifactDirectory = Join-Path $resolvedRepo "smoke-artifacts\$runId"
    New-Item -ItemType Directory -Path $script:ArtifactDirectory -Force | Out-Null
    Write-Host "==> Artifacts: smoke-artifacts\$runId"

    $script:CurrentStage = "create or reuse virtual environment"
    if ([System.IO.Path]::IsPathRooted($VenvPath)) {
        $venvDirectory = [System.IO.Path]::GetFullPath($VenvPath)
    }
    else {
        $venvDirectory = [System.IO.Path]::GetFullPath(
            (Join-Path $resolvedRepo $VenvPath)
        )
    }
    $repoPrefix = $resolvedRepo.TrimEnd("\") + "\"
    Assert-Condition `
        ($venvDirectory.StartsWith(
            $repoPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) `
        "VenvPath must remain inside the AlphaOS repository."
    $venvPython = Join-Path $venvDirectory "Scripts\python.exe"
    $venvVersion = Get-PythonMinorVersion -Executable $venvPython
    if (-not (Test-CompatiblePythonVersion -Version $venvVersion)) {
        $basePython = Find-CompatiblePython -RequestedPath $PythonPath
        $baseVersion = Get-PythonMinorVersion -Executable $basePython
        Write-Host "==> Rebuilding $VenvPath with compatible CPython $baseVersion"
        Invoke-LoggedNative `
            -Stage "create compatible .venv" `
            -FilePath $basePython `
            -Arguments @("-m", "venv", "--clear", $venvDirectory) `
            -LogName "venv-create.log"
    }
    Assert-Condition (Test-Path -LiteralPath $venvPython -PathType Leaf) `
        "Scripts\python.exe was not found in .venv."
    Write-Host "==> $VenvPath is ready"

    Invoke-LoggedNative `
        -Stage "install requirements.txt" `
        -FilePath $venvPython `
        -Arguments @("-m", "pip", "install", "-r", "requirements.txt") `
        -LogName "pip-requirements.log"
    Invoke-LoggedNative `
        -Stage "install pytest" `
        -FilePath $venvPython `
        -Arguments @("-m", "pip", "install", "pytest") `
        -LogName "pip-pytest.log"

    $script:CurrentStage = "verify Python runtime imports"
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $runtimeProbe = @(
            & $venvPython -c `
                "import fastapi, numpy, pandas, pydantic_core, pytest" 2>&1
        )
        $runtimeProbeExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $cleanRuntimeProbe = @(
        $runtimeProbe | ForEach-Object {
            Protect-Secrets ([string]$_)
        }
    )
    [System.IO.File]::WriteAllLines(
        (Join-Path $script:ArtifactDirectory "python-runtime-initial.log"),
        [string[]]$cleanRuntimeProbe,
        $script:Utf8NoBom
    )
    if ($runtimeProbeExitCode -ne 0) {
        Write-Host "==> Existing .venv packages are incompatible; repairing them"
        Invoke-LoggedNative `
            -Stage "repair requirements.txt installation" `
            -FilePath $venvPython `
            -Arguments @(
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--force-reinstall",
                "--no-cache-dir",
                "-r",
                "requirements.txt"
            ) `
            -LogName "pip-requirements-repair.log"
        Invoke-LoggedNative `
            -Stage "repair pytest installation" `
            -FilePath $venvPython `
            -Arguments @(
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--force-reinstall",
                "--no-cache-dir",
                "pytest"
            ) `
            -LogName "pip-pytest-repair.log"
    }
    Invoke-LoggedNative `
        -Stage "verify Python runtime imports" `
        -FilePath $venvPython `
        -Arguments @(
            "-c",
            "import fastapi, numpy, pandas, pydantic_core, pytest"
        ) `
        -LogName "python-runtime-final.log"

    $pytestBaseTemp = Join-Path $script:ArtifactDirectory "pytest-temp"
    $pytestCache = Join-Path $script:ArtifactDirectory "pytest-cache"
    New-Item -ItemType Directory -Path $pytestBaseTemp -Force | Out-Null
    New-Item -ItemType Directory -Path $pytestCache -Force | Out-Null
    $env:TEMP = $pytestBaseTemp
    $env:TMP = $pytestBaseTemp
    $env:TMPDIR = $pytestBaseTemp
    $pytestBaseTempArgument = $pytestBaseTemp.Replace("\", "/")
    $pytestCacheArgument = $pytestCache.Replace("\", "/")
    $env:PYTEST_ADDOPTS = (
        "--basetemp=" + $pytestBaseTempArgument +
        " -o cache_dir=" + $pytestCacheArgument
    )
    Invoke-LoggedNative `
        -Stage "run automated tests" `
        -FilePath $venvPython `
        -Arguments @("-m", "pytest", "-q", "tests") `
        -LogName "pytest.log"

    $script:CurrentStage = "verify port $Port is available"
    $portClient = New-Object System.Net.Sockets.TcpClient
    $portOccupied = $false
    try {
        $connectAttempt = $portClient.BeginConnect(
            "127.0.0.1",
            $Port,
            $null,
            $null
        )
        if ($connectAttempt.AsyncWaitHandle.WaitOne(500)) {
            try {
                $portClient.EndConnect($connectAttempt)
                $portOccupied = $portClient.Connected
            }
            catch {
                $portOccupied = $false
            }
        }
        $connectAttempt.AsyncWaitHandle.Close()
    }
    finally {
        $portClient.Close()
    }
    Assert-Condition (-not $portOccupied) `
        "Port $Port is already in use; refusing to connect to an existing service."

    $script:CurrentStage = "start uvicorn"
    $script:UvicornStdout = Join-Path $script:ArtifactDirectory "uvicorn.stdout.log"
    $script:UvicornStderr = Join-Path $script:ArtifactDirectory "uvicorn.stderr.log"
    Write-Host "==> Starting uvicorn backend.main:app (127.0.0.1:$Port)"
    $script:UvicornProcess = Start-Process `
        -FilePath $venvPython `
        -ArgumentList @(
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            [string]$Port
        ) `
        -WorkingDirectory $resolvedRepo `
        -RedirectStandardOutput $script:UvicornStdout `
        -RedirectStandardError $script:UvicornStderr `
        -WindowStyle Hidden `
        -PassThru

    $script:CurrentStage = "wait for uvicorn readiness"
    $baseUri = "http://127.0.0.1:$Port"
    $ready = $false
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        $script:UvicornProcess.Refresh()
        if ($script:UvicornProcess.HasExited) {
            throw "The newly started uvicorn exited before readiness with code $($script:UvicornProcess.ExitCode)."
        }
        try {
            $probe = Invoke-WebRequest `
                -Uri "$baseUri/api/health" `
                -Method GET `
                -UseBasicParsing `
                -TimeoutSec 2
            if ($probe.StatusCode -eq 200) {
                $ready = $true
                break
            }
        }
        catch {
            # The server can refuse connections during normal startup.
        }
        Start-Sleep -Milliseconds 500
    }
    Assert-Condition $ready "uvicorn did not become healthy within 15 seconds."

    $script:CurrentStage = "identify uvicorn listener process"
    $listeners = @(
        Get-NetTCPConnection `
            -LocalAddress "127.0.0.1" `
            -LocalPort $Port `
            -State Listen `
            -ErrorAction Stop
    )
    Assert-Condition ($listeners.Count -eq 1) `
        "Expected exactly one uvicorn listener on 127.0.0.1:$Port."
    $listenerProcessId = [int]$listeners[0].OwningProcess
    Assert-Condition `
        (Test-IsDescendantProcess `
            -ChildProcessId $listenerProcessId `
            -AncestorProcessId $script:UvicornProcess.Id) `
        "The healthy listener is not owned by the uvicorn process started by this script."
    $script:UvicornServerProcessId = $listenerProcessId

    $health = Invoke-ApiJson `
        -Stage "check GET /api/health" `
        -Method GET `
        -Uri "$baseUri/api/health" `
        -ArtifactName "health.json"
    Assert-Condition ($health.status -eq "ok") `
        "/api/health status was not ok."

    $pandaStatus = Invoke-ApiJson `
        -Stage "check GET /api/pandadata/status" `
        -Method GET `
        -Uri "$baseUri/api/pandadata/status" `
        -ArtifactName "pandadata-status.json"
    Assert-Condition ([bool]$pandaStatus.configured) `
        "/api/pandadata/status did not report configured=true."

    $promptBase64 = "5YiG5p6QIDAwMDAwMS5TWiDlnKggMjAyNCDlubTnmoTooajnjrDvvIzor4bliKvkuLvopoHpo47pmanlubbnlJ/miJDnoJTnqbbmiqXlkYrjgII="
    $prompt = [System.Text.Encoding]::UTF8.GetString(
        [System.Convert]::FromBase64String($promptBase64)
    )
    $promptRequest = @{ prompt = $prompt }
    $requiredAgents = @("research", "risk", "report")

    $plan = Invoke-ApiJson `
        -Stage "call POST /api/plan" `
        -Method POST `
        -Uri "$baseUri/api/plan" `
        -ArtifactName "plan.json" `
        -Body $promptRequest
    $planAgents = @(
        $plan.steps | ForEach-Object { [string]$_.agent } | Sort-Object -Unique
    )
    foreach ($requiredAgent in $requiredAgents) {
        Assert-Condition ($planAgents -contains $requiredAgent) `
            "/api/plan is missing required expert $requiredAgent."
    }
    Assert-Condition ($planAgents -notcontains "manager") `
        "/api/plan incorrectly placed Manager in an expert step."
    Write-Host "==> Dynamic Manager plan includes research, risk, and report (order is not fixed)"

    $marketDataRequest = @{
        symbols = @("000001.SZ")
        start_date = "20240101"
        end_date = "20241231"
        fields = @("trade_date", "symbol", "close", "volume")
    }
    $null = Invoke-ApiJson `
        -Stage "call POST /api/market-data" `
        -Method POST `
        -Uri "$baseUri/api/market-data" `
        -ArtifactName "market-data.json" `
        -Body $marketDataRequest `
        -TimeoutSec 300

    $taskResponse = Invoke-ApiJson `
        -Stage "call POST /api/tasks" `
        -Method POST `
        -Uri "$baseUri/api/tasks" `
        -ArtifactName "tasks.json" `
        -Body $promptRequest `
        -TimeoutSec 900

    $taskPlanAgents = @(
        $taskResponse.plan.steps |
            ForEach-Object { [string]$_.agent } |
            Sort-Object -Unique
    )
    foreach ($requiredAgent in $requiredAgents) {
        Assert-Condition ($taskPlanAgents -contains $requiredAgent) `
            "/api/tasks plan is missing required expert $requiredAgent."
    }
    Assert-Condition ($taskPlanAgents -notcontains "manager") `
        "/api/tasks plan incorrectly placed Manager in an expert step."

    $resultProperties = @($taskResponse.results.PSObject.Properties)
    Assert-Condition ($resultProperties.Count -eq @($taskResponse.plan.steps).Count) `
        "/api/tasks result count does not match the dynamic plan step count."
    $resultStepIds = @(
        $resultProperties | ForEach-Object { [string]$_.Name }
    )
    foreach ($planStep in @($taskResponse.plan.steps)) {
        Assert-Condition ($resultStepIds -contains [string]$planStep.id) `
            "/api/tasks has no result for planned step $($planStep.id)."
    }
    foreach ($resultProperty in $resultProperties) {
        Assert-Condition ($resultProperty.Value.status -eq "completed") `
            ("Expert step " + $resultProperty.Name + " was not completed; status=" +
                $resultProperty.Value.status + ".")
    }
    Assert-Condition `
        ($taskResponse.aggregation.completion_status -eq "completed") `
        ("aggregation.completion_status was " +
            $taskResponse.aggregation.completion_status + ", not completed.")

    $eventTypes = @($taskResponse.events | ForEach-Object { [string]$_.type })
    $requiredEvents = @(
        "plan_created",
        "step_started",
        "tool_called",
        "step_completed",
        "synthesis_started",
        "task_completed"
    )
    foreach ($eventType in $requiredEvents) {
        Assert-Condition ($eventTypes -contains $eventType) `
            "/api/tasks event stream is missing $eventType."
    }

    $summary = [ordered]@{
        status = "completed"
        timestamp = (Get-Date).ToString("o")
        port = $Port
        virtual_environment = $VenvPath
        plan_agents = $planAgents
        task_plan_agents = $taskPlanAgents
        completed_steps = @($resultProperties | ForEach-Object { $_.Name })
        aggregation_completion_status = $taskResponse.aggregation.completion_status
        required_events = $requiredEvents
    }
    Write-JsonArtifact -Name "smoke-summary.json" -Value $summary
    Write-Host "==> Full real Agent workflow smoke test passed"
}
catch {
    $exitCode = 1
    $failureMessage = Protect-Secrets $_.Exception.Message
    $failure = [ordered]@{
        status = "failed"
        timestamp = (Get-Date).ToString("o")
        first_failure_stage = $script:CurrentStage
        error = $failureMessage
    }
    if ($script:ArtifactDirectory) {
        Write-JsonArtifact -Name "smoke-failure.json" -Value $failure
    }
    Write-Host (
        "SMOKE FAILED at [" + $script:CurrentStage + "]: " + $failureMessage
    ) -ForegroundColor Red
}
finally {
    if ($null -ne $script:UvicornProcess) {
        try {
            if ($null -eq $script:UvicornServerProcessId) {
                $ownedListeners = @(
                    Get-NetTCPConnection `
                        -LocalAddress "127.0.0.1" `
                        -LocalPort $Port `
                        -State Listen `
                        -ErrorAction SilentlyContinue |
                        Where-Object {
                            Test-IsDescendantProcess `
                                -ChildProcessId ([int]$_.OwningProcess) `
                                -AncestorProcessId $script:UvicornProcess.Id
                        }
                )
                if ($ownedListeners.Count -eq 1) {
                    $script:UvicornServerProcessId = [int](
                        $ownedListeners[0].OwningProcess
                    )
                }
            }
            if ($null -ne $script:UvicornServerProcessId) {
                Stop-TrackedProcess `
                    -ProcessId $script:UvicornServerProcessId
            }
            if ($script:UvicornProcess.Id -ne $script:UvicornServerProcessId) {
                Stop-TrackedProcess -ProcessId $script:UvicornProcess.Id
            }
            for ($attempt = 1; $attempt -le 40; $attempt++) {
                $remainingListener = Get-NetTCPConnection `
                    -LocalAddress "127.0.0.1" `
                    -LocalPort $Port `
                    -State Listen `
                    -ErrorAction SilentlyContinue
                if ($null -eq $remainingListener) {
                    break
                }
                Start-Sleep -Milliseconds 250
            }
            Assert-Condition ($null -eq $remainingListener) `
                "The uvicorn listener started by this script is still running."
            Write-Host "==> Stopped the uvicorn process started by this script"
        }
        catch {
            $cleanupMessage = Protect-Secrets $_.Exception.Message
            Write-Host "Error while stopping uvicorn: $cleanupMessage" -ForegroundColor Yellow
            if ($exitCode -eq 0) {
                $exitCode = 1
            }
        }
    }
    Sanitize-File -Path $script:UvicornStdout
    Sanitize-File -Path $script:UvicornStderr
}

exit $exitCode
