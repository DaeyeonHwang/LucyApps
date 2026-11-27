# 바다 구조대 앱 아이콘 만들기 (구명튜브 모양). 실행: powershell -File tools\make-icons.ps1
Add-Type -AssemblyName System.Drawing
$out = Join-Path $PSScriptRoot '..\sea-rescue\icons'
New-Item -ItemType Directory -Force $out | Out-Null

function Draw-Icon([int]$size, [string]$path, [bool]$maskable) {
  $bmp = New-Object System.Drawing.Bitmap $size, $size
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = 'AntiAlias'
  $teal = [System.Drawing.Color]::FromArgb(63,148,138)
  $coral = [System.Drawing.Color]::FromArgb(226,100,79)
  $cream = [System.Drawing.Color]::FromArgb(251,247,239)
  $wave = [System.Drawing.Color]::FromArgb(120,196,186)

  if ($maskable) {
    $g.Clear($teal)
  } else {
    $g.Clear([System.Drawing.Color]::Transparent)
    $r = [int]($size * 0.22)
    $gp = New-Object System.Drawing.Drawing2D.GraphicsPath
    $gp.AddArc(0, 0, $r*2, $r*2, 180, 90)
    $gp.AddArc($size-$r*2-1, 0, $r*2, $r*2, 270, 90)
    $gp.AddArc($size-$r*2-1, $size-$r*2-1, $r*2, $r*2, 0, 90)
    $gp.AddArc(0, $size-$r*2-1, $r*2, $r*2, 90, 90)
    $gp.CloseFigure()
    $g.FillPath((New-Object System.Drawing.SolidBrush $teal), $gp)
    $g.SetClip($gp)
  }

  # 물결
  $wb = New-Object System.Drawing.SolidBrush $wave
  $g.FillEllipse($wb, [int](-$size*0.2), [int]($size*0.78), [int]($size*0.8), [int]($size*0.5))
  $g.FillEllipse($wb, [int]($size*0.45), [int]($size*0.8), [int]($size*0.8), [int]($size*0.5))

  # 구명튜브: 크림색 바탕 + 산호색 네 조각
  $scale = if ($maskable) { 0.52 } else { 0.66 }
  $d = [int]($size * $scale); $x = [int](($size - $d) / 2); $y = [int](($size - $d) / 2 - $size*0.03)
  $thick = [single]($d * 0.26)
  $inset = [single]($thick / 2)
  $rect = New-Object System.Drawing.RectangleF ([single]($x + $inset)), ([single]($y + $inset)), ([single]($d - $thick)), ([single]($d - $thick))
  $g.DrawEllipse((New-Object System.Drawing.Pen $cream, $thick), $rect)
  $cp = New-Object System.Drawing.Pen $coral, $thick
  foreach ($start in 20, 110, 200, 290) { $g.DrawArc($cp, $rect, $start, 50) }

  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
}

Draw-Icon 192 (Join-Path $out 'icon-192.png') $false
Draw-Icon 512 (Join-Path $out 'icon-512.png') $false
Draw-Icon 512 (Join-Path $out 'maskable-512.png') $true
Draw-Icon 180 (Join-Path $out 'apple-touch-icon.png') $true
"icons done"
