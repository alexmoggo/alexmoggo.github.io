# Tesla Solar Charging Controller: Project Brief

## Goal
Automatically control home charging of a Tesla from rooftop solar, at **$0 ongoing cost**, with **no always-on home device**. Runs as a scheduled cloud job.

## Hard constraints
- Zero spend. No paid services, no purchased domain, no hardware.
- Do not poll the car on a schedule. Car API calls cost money (see Cost control).
- Never commit secrets. The private key, client secrets and tokens go in GitHub Actions secrets only.
- Start in **dry-run mode** (log decisions, send no car commands) until the owner approves going live.

## Hardware and site facts
| Item | Value |
|---|---|
| Car | Tesla Model Y, 2023 (requires signed commands via the Vehicle Command Protocol) |
| Charger | Tesla Mobile Connector on a 10 A outlet. Car reports **10 A max**. No network or API on the charger |
| Charge power | about 2.3 kW at 10 A and 230 V |
| Inverter | Sungrow **SG5K-D** (5 kW single-phase string inverter, no battery) |
| Comms dongle | Sungrow **WiFi V31** (older module, not WiNet-S). No local Modbus TCP. Use the cloud API |
| Grid or consumption meter | **None.** House load is not measured |
| Monitoring | iSolarCloud (owner has a normal login) |
| Time zone | Australia/Brisbane (no daylight saving). Confirmed by owner |

## Control rules
1. **Free window, 11:00 to 15:00 local, every day:** charge at **10 A** regardless of solar.
2. **Outside the free window:** surplus = PV power − **1.0 kW assumed house load**.
   - amps = floor(surplus ÷ 230 V), capped at 10 A
   - If amps is below the car's minimum charge current, stop charging
   - The minimum is believed to be about 5 A but is unverified. Determine it from Tesla docs or `set_charging_amps` responses
3. **Charge limit:** use the limit set in the Tesla app. Never change it.
4. **No overnight fallback.** Outside daylight with no surplus, do nothing.
5. **Hysteresis:** require 2 consecutive qualifying readings before starting or stopping, to avoid cycling on clouds.
6. **Run interval:** every 5 minutes. Sungrow cloud data updates about every 5 minutes, so faster polling is pointless.
7. **Only act when state changes.** If already charging at the right amps, send nothing.

## Architecture
- **Key hosting:** public repo `alexmoggo/alexmoggo.github.io` (GitHub Pages, branch `main`, currently only a README).
  Add:
  ```
  .nojekyll                                            (empty file, required or .well-known is not published)
  .well-known/appspecific/com.tesla.3p.public-key.pem  (public key only)
  ```
  Tesla Allowed Origin: `https://alexmoggo.github.io`
- **Controller code:** decide whether it lives in this repo or a separate repo (see Verify item 1).
- **Scheduler:** GitHub Actions cron, every 5 minutes.
- **Solar data:** iSolarCloud OpenAPI (developer portal https://developer-api.isolarcloud.com/). Python package `pysolarcloud` is an option.
- **Car control:** Tesla Fleet API with signed commands (Tesla `vehicle-command` tooling or equivalent). Commands needed: `charge_start`, `charge_stop`, `set_charging_amps`, `wake_up` (only when needed).

## Owner setup steps (guide the owner through these)
1. **Tesla developer app** at developer.tesla.com
   - Allowed Origin `https://alexmoggo.github.io`, plus a redirect URI for OAuth
   - Scopes: `vehicle_device_data`, `vehicle_cmds`, `vehicle_charging_cmds`
   - Add a payment method and set the **billing limit to $1** (the default limit of 0 disables the app)
2. Generate a prime256v1 key pair. Commit the public key to the Pages repo. Store the private key as a GitHub secret.
3. Call the Partner Account register endpoint for domain `alexmoggo.github.io`.
4. Pair the key with the car: open `https://tesla.com/_ak/alexmoggo.github.io` in the Tesla app.
5. **iSolarCloud developer app:** create an account, create an app (OAuth2, redirect URL), wait for Sungrow approval, then collect the Appkey, Secret Key and Application ID.

## Cost control (Tesla Fleet API)
- Pay-per-use with a $10/month discount for individual developers. Every response below status 500 is billable, including errors.
- Approximate rates: wake about $0.02, data request about $0.002, command about $0.001.
- Wakes are the most expensive call. Limits are 3 wakes/min and 30 commands/min.
- **Design rules:**
  - Read PV from Sungrow every run. Touch the car only when the decision changes.
  - Infer car state from command responses (`disconnected`, `complete`, `is_charging`, `not_charging`, `requested`, `no_power`) rather than polling `vehicle_data`.
  - Check whether the vehicle is online before waking it.
  - Log every billable call with a running monthly count. Target under $3/month.

## Verify before building (unconfirmed items)
1. **GitHub Actions free minutes.** A 5-minute cron is about 8,600 runs/month. Confirm whether this is free on a public repo and whether a private repo would exceed the free allowance. Also confirm whether GitHub disables scheduled workflows after a period of repo inactivity, and how to prevent that.
2. **Token persistence.** Tesla and iSolarCloud refresh tokens may rotate. Design how a new refresh token is saved between Actions runs (for example, updating a repo secret via the GitHub API with a fine-grained token).
3. **iSolarCloud re-authorisation.** `pysolarcloud` notes that the OAuth flow re-prompts the user when tokens expire. Determine how often this happens and whether the API-key login variant avoids it.
4. **Signed commands from GitHub Actions.** Confirm the cleanest way to sign commands in a stateless runner (Tesla `tesla-control` over internet transport, or the HTTP proxy started per run).
5. **Correct iSolarCloud data point** for current PV power on an SG5K-D. Compare against the iSolarCloud app.
6. **Car minimum amps** via the Fleet API.
7. **Whether the Fleet API $10 monthly discount is still active.** A third-party README claimed it is being discontinued. Tesla's billing page still listed it on 2 Nov 2026.
8. ~~Free window time zone~~ Confirmed: Australia/Brisbane.

## Acceptance tests
- Dry run for 2 to 3 days. The log shows each decision, the PV reading and the amps it would set.
- The free window starts charging at 10 A at 11:00 and stops at 15:00 if there is no surplus.
- Passing cloud does not cause more than one start/stop per 10 minutes.
- Monthly Fleet API usage estimate is under $3.
- No secrets appear in either repo.

## Out of scope
- Home battery, grid meter, Wall Connector, Bluetooth control, paid services (Charge HQ, Teslemetry, Overflow EV).

## Privacy rule (owner instruction)
Never commit names, serial numbers, VINs, plant IDs, addresses, tokens or keys. These live only in GitHub Actions secrets. Workflow logs are public: never print them.

## Implementation
See `docs/SETUP.md`. Code: `controller/` (decision logic in `decide.py`, tests in `tests/`).
