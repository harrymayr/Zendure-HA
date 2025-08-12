name: Feature Request
description: Request a feature
title: "[Feature] <Replace this part>"
labels:
  - "feature request"
body:
  - type: textarea
    id: description
    attributes:
      label: Describe the feature
      description: A clear and concise description of what the feature is
    validations:
      required: true
  - type: dropdown
    id: device
    attributes:
      label: What device is this for?
      options:
        - SF2400 AC
        - SF800 Pro
        - SF800
        - Hyper2000
        - Hub2000
        - Hub1200
        - Ace1500
        - Aio2400
        - SuperBase V6400
        - Zendure Manager
    validations:
      required: true
  - type: textarea
    id: other
    attributes:
      label: Other Information
      description: Anything else we should know?
