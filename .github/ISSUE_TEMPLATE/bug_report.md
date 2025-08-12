---
name: Bug report
about: Create a report to help us improve
title: "[Bug] <Replace this part>"
labels:
  - bug
assignees: ''

body:
  - type: input
    id: ha-version
    attributes:
      label: Home Assistant Version
      description: The version of Home Assistant
      placeholder: 2025.5.1
    validations:
      required: true
  - type: input
    id: zenha-version
    attributes:
      label: Zendure Integration Version
      description: The version of this integration you're using
      placeholder: v1.1.3
    validations:
      required: true
  - type: textarea
    id: description
    attributes:
      label: Describe the bug
      description: A clear and concise description of what the bug is.
      placeholder: Tell us what you see!
    validations:
      required: true
  - type: textarea
    id: reproduce
    attributes:
      label: To Reproduce
      description: How can we replicate this?
      placeholder: |
        1. Go to '...'
        2. Click on '...'
        3. Scroll down to '...'
        4. See error
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: Expected Behaviour
      description: What did you expect to happen?
    validations:
      required: true
  - type: dropdown
    id: device
    attributes:
      label: What device are you using?
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
    validations:
      required: true
  - type: textarea
    id: diagnostic
    attributes:
      label: Diagnostic Output
      placeholder: Go to the Home Assistant Bambu Lab Integration, and click Download Diagnostics and drag it here
      description: |
        Tip: You can attach images or log files by clicking this area to highlight it and then dragging files in.
      render: shell
    validations:
      required: true
  - type: textarea
    id: logs
    attributes:
      label: Log Extracts
      description: Any log information?
      render: shell
  - type: textarea
    id: other
    attributes:
      label: Other Information
      description: Anything else we should know?
