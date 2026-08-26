export function browserWindowChrome(platform = process.platform) {
  return platform === 'darwin'
    ? {
        titleBarStyle: 'hidden',
        trafficLightPosition: { x: 14, y: 11 },
      }
    : { titleBarStyle: 'default' };
}
