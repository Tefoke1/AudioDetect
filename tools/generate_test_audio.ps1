# Generate fictional speech fixtures locally with Windows SAPI. No real call audio is used.
$ErrorActionPreference = 'Stop'
$fixtureRoot = Join-Path $PSScriptRoot '../android/app/src/androidTest/assets'
New-Item -ItemType Directory -Force -Path $fixtureRoot | Out-Null
$voice = New-Object -ComObject SAPI.SpVoice
foreach ($language in @('en', 'ru')) {
    $description = if ($language -eq 'ru') { '*Russian*' } else { '*English*' }
    $selectedVoice = $voice.GetVoices() | Where-Object { $_.GetDescription() -like $description } | Select-Object -First 1
    if (-not $selectedVoice) { throw "Install a Windows $language speech voice before generating fixtures." }
    $voice.Voice = $selectedVoice
    $stream = New-Object -ComObject SAPI.SpFileStream
    $stream.Open((Join-Path $fixtureRoot "demo-$language.wav"), 3, $false)
    $voice.AudioOutputStream = $stream
    $words = if ($language -eq 'ru') { 'Договор согласован. Оплату нужно отправить в пятницу. Проект готов, осталось проверить смету. Спасибо.' } else { 'We approved the contract. The payment deadline is Friday. Please send the revised budget by email. Thank you.' }
    [void]$voice.Speak($words)
    $stream.Close()
}
