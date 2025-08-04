<p align="center">
  <img src="https://zendure.com/cdn/shop/files/zendure-logo-infinity-charge_240x.png?v=1717728038" alt="Logo">
</p>

# Zendure Home Assistant Integration
This Home Assistant integration connects your Zendure devices to Home Assistant, making all reported parameters available as entities. You can track battery levels, power input/output, manage charging settings, and integrate your Zendure devices into your home automation routines. The integration also provides a power manager feature that can help balance energy usage across multiple devices when a P1 meter entity is supplied.


[![hacs][hacsbadge]][hacs] [![releasebadge]][release] [![Build Status][buildstatus-shield]][buildstatus-link] [![License][license-shield]](LICENSE.md)


## Overview

- **Installation:**
  - Tutorials
    - [Domotica & IoT 🇺🇸](https://iotdomotica.nl/tutorial/install-zendure-home-assistant-integration-tutorial)
    - [twoenter blog 🇺🇸](https://www.twoenter.nl/blog/en/smarthome-en/zendure-home-battery-home-assistant-integration/) or [twoenter blog 🇳🇱](https://www.twoenter.nl/blog/home-assistant-nl/zendure-thuisaccu-integratie-met-home-assistant/)


- **Configuration:**
  - Power Cluster
  - Zendure Manager
    - Power distribution strategy
  - [Local Mqtt](https://github.com/Zendure/Zendure-HA/wiki/Local-Mqtt)
  - Home Assistent Energy Dashboard
  
- **Supported devices:**
  - Ace1500
  - Aio2400
  - Hyper2000
  - Hub1200
  - Hub2000
  - SF800
  - SF800 Pro
  - SF2400 AC
  - SuperBase V6400
  
- **Device Automation:**
  - Cheap hours.

## Minimum Requirements
- [Home Assistant](https://github.com/home-assistant/core) 2025.5+

## Installation

### HACS (Home Assistant Community Store)

To install via HACS:

1. Navigate to HACS -> Integrations -> "+ Explore & Download Repos".
2. Search for "Node-RED Companion".
3. Click on the result and select "Download this Repository with HACS".
4. Refresh your browser (due to a known HA bug that may not update the integration list immediately).
5. Go to "Settings" in the Home Assistant sidebar, then select "Devices and Services".
6. Click the blue [+ Add Integration] button at the bottom right, search for "Node-RED", and install it.
 
   [![Set up a new integration in Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=zendure_ha)


## Contributing

Contributions are welcome! If you're interested in contributing, please review our [Contribution Guidelines](CONTRIBUTING.md) before submitting a pull request or issue.

## Support

If you find this project helpful and want to support its development, consider buying me a coffee!  
[![Buy Me a Coffee][buymecoffeebadge]][buymecoffee]

---

[buymecoffee]: https://www.buymeacoffee.com/fireson
[buymecoffeebadge]: https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png
[license-shield]: https://img.shields.io/github/license/zendure/zendure-ha.svg?style=for-the-badge
[hacs]: https://github.com/zendure/zendure-ha
[hacsbadge]: https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge
[release]: https://github.com/zendure/zendure-ha/releases
[releasebadge]: https://img.shields.io/github/v/release/zendure/zendure-ha?style=for-the-badge
[buildstatus-shield]: https://img.shields.io/github/actions/workflow/status/zendure/zendure-ha/push.yml?branch=main&style=for-the-badge
[buildstatus-link]: https://github.com/zendure/zendure-ha/actions


## License

MIT License
