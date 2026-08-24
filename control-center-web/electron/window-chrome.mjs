export function browserWindowChrome(platform = process.platform) {
  return platform === 'darwin'
    ? {
        titleBarStyle: 'hiddenInset',
        trafficLightPosition: { x: 14, y: 13 },
      }
    : { titleBarStyle: 'default' };
}
