# In practice

These are the end-to-end scenarios in
[`tests/ha/test_scenarios.py`](../tests/ha/test_scenarios.py), each run against a
whole house in a real Home Assistant. Points are the defaults, the house's night
window is 10 p.m. to 6 a.m., and the numbers in brackets are scores.

| What happens | House | What SIEM does |
| --- | --- | --- |
| A family evening: switches, the fridge, the kettle, the TV, kids in and out | Family | Nothing |
| A business trip: you away, your partner home using Apple Home, the kids home | Family: your partner's person entity follows their phone and watch | Nothing |
| The same trip with your partner not among the residents | Vacant | Alerts, until you set the mode to family |
| Kids in the yard and through the gate | Family | Nothing |
| Someone tries codes until the keypad locks out, 2 a.m. | Family, in bed | Verify and break glass |
| A kid comes home with their code | Family | Nothing |
| The mail carrier rings the doorbell | Vacant | Nothing (18) |
| A parcel at the door at 11 p.m. | Vacant | Verify (27) |
| A delivery through the side gate | Vacant | Verify (43) |
| Someone lingers in the backyard for 40 minutes at 1 a.m. | Vacant | Verify, once |
| Someone comes through the side gate at 1 a.m. | Vacant | Deter (64) |
| Gate, back door, kitchen, by day | Vacant | Alarm; the trigger a minute later |
| In through a window with no sensor: bedroom, hall, closet | Vacant | Verify, deter, alarm |
| The front door at 2 a.m., then the hall | Vacant | Deter, then alarm |
| A neighbor with a key nobody mentioned | Vacant | Break glass and alarm |
| Home through the garage, the phone 30 seconds late | Vacant, then family | Verify and alarm alerts, then the score drops to 0; the trigger never turns on |
| Home with the phone on time | Family | Nothing |
| Home at 11:30 p.m. with a code, the phone late | Vacant, then guest | Verify for someone on the porch at night, then nothing |
| A friend house-sits, their phone seen by your Wi-Fi | Guest | Nothing; vacant again half an hour after they leave |
| The friend comes in with a key before their phone joins the Wi-Fi | Vacant, then guest | Break glass and alarm alerts, then the score drops to 0; the trigger never turns on |
| The cleaner's code and three hours of cleaning | Guest | Nothing; vacant again an hour after they leave |
| A neighbor on the calendar as `Guest:` | Guest | Nothing |
| The cleaners' day on a Workday sensor: a key, every room, the water | Service from 6 a.m. | Nothing; the night before, still vacant, a back door at 1 a.m. is a deter |
| Friends staying, on a helper and a `Guest:` event | Guest | Nothing; vacant again two hours after the helper turns off and the house goes quiet |
| Unlocking for the plumber from the app | Guest | Nothing |
| Opening the garage from the app for a delivery | Guest | Nothing |
| The dog, on weak motion sensors, for six hours | Vacant | Nothing |
| The pet sitter leaves, then a break-in that night | Vacant | Alarm: the dog didn't hold guest mode open |
| Presence Simulation: lights, a smart plug, the TV | Vacant | Nothing |
| A sunset automation, a slow light, a scene by area | Vacant | Nothing |
| The app or Apple Home, from far away | Vacant | Nothing |
| A light switched by its own app, such as a Hue schedule | Vacant | Verify; see below |
| Z-Wave JS restarts | Vacant | Nothing |
| The Z-Wave stick dies on vacation | Vacant | Verify after two minutes, break glass after an hour |
| Someone lingers in the backyard at 1 a.m. while you sleep | Family, in bed | Verify, once |
| Someone comes through the side gate at 1 a.m. while you sleep | Family, in bed | Deter (64) |
| Gate, back door, kitchen, at 3 a.m. | Family, in bed | Alarm; the trigger a minute later |
| A window opens at 2:30 a.m. with nobody up, then motion in that room | Family, in bed | Deter, then alarm |
| Letting the dog out at 2 a.m. | Family, in bed | Nothing |
| Ten minutes in the kitchen, then out the back door | Family, in bed | Nothing |
| A kid up for water | Family, in bed | Nothing |
| Your partner home at 1 a.m., their phone on time | Family, in bed | Nothing |
| A teenager home at 11:45 p.m. with a code | Family, in bed | Verify for someone at the door in the dark, then nothing |
| A teenager sneaking out | Family, in bed | Nothing; see below |
| A burglar at the back door a minute after someone walked down the hall | Family, in bed | Nothing; see below |
| The panel armed night at 11:30 p.m. | Family, then in bed | Bedtime comes from the panel, not the clock |
| Your own bedtime sensor and the panel, both picked | In bed when either says so | The clock only stands in for one that is unavailable |
| Someone through the gate and at the back door at 3 a.m. while a house-sitter sleeps | Guest, in bed | Verify, deter, alarm: guests go to bed with the night window |
| The house-sitter lets the dog out at 2 a.m. | Guest, in bed | Nothing |
| A window and then motion at 2:30 a.m., with guest mode forced and forgotten | Guest, in bed | Deter, then alarm: a forced guest still goes to bed |

The rows marked *see below* are the judgment calls described under
[Known limits](../README.md#known-limits): a light switched outside Home
Assistant looks like a hand on the switch, and at night the order of events
decides who is coming and who is going.
