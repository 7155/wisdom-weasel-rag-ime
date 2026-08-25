# PAW ego-browser runtime

The ego-browser runtime is a product component, not a user-installed app.

- PAW launches one isolated Chromium profile.
- The vendored MIT host attaches to PAW's loopback DevTools port.
- The product build compiles the vendored Node packages with
  `scripts/build_ego_browser_runtime.sh`.
- The Sidecar installer copies that verified runtime with the Python control
  service and the managed Pi Skill.

Never download or mount the upstream ego lite DMG to repair PAW. If the Browser
app reports that the runtime is unavailable, use PAW Runtime diagnostics and
repair/reinstall the PAW product generation so browser code, Skill, Sidecar,
and UI remain on one provenance boundary.
