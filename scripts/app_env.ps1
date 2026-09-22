# 双端开发使用同一套 D 盘 SDK；只影响当前终端，不替换系统 Java。
$AppTools = 'D:\CodexWorkspace\app-toolchain'
$env:FLUTTER_ROOT = Join-Path $AppTools 'flutter'
$env:ANDROID_HOME = Join-Path $AppTools 'android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:ANDROID_USER_HOME = Join-Path $AppTools 'cache\android'
$env:ANDROID_AVD_HOME = Join-Path $AppTools 'cache\avd'
$env:GRADLE_USER_HOME = Join-Path $AppTools 'cache\gradle'
$env:PUB_CACHE = Join-Path $AppTools 'cache\pub'
$env:FLUTTER_STORAGE_BASE_URL = 'https://storage.flutter-io.cn'
$env:PUB_HOSTED_URL = 'https://pub.flutter-io.cn'
$env:JAVA_HOME = Join-Path $AppTools 'jdk-17.0.20.1+1'
$env:Path = "$env:FLUTTER_ROOT\bin;$env:ANDROID_HOME\platform-tools;$env:ANDROID_HOME\cmdline-tools\latest\bin;$env:JAVA_HOME\bin;$env:Path"
