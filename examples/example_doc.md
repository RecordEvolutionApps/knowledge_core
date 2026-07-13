---
id: device.examplevendor.examplemodel
title: "ExampleVendor ExampleModel controller - Modbus TCP"
kind: device
summary: >-
  One-line description shown in list results (max 250 chars). Say what the
  device is, which protocol, and whether the map is verified.
protocol: modbus
drivers: [modbus-tcp]
vendor: "ExampleVendor"
model: "ExampleModel 100/200"
equipment_type: air_compressor
keywords: [compressor, example, screw]
aliases: ["EM-100", "EM-200"]
verified: unverified
---

## Overview
Two or three sentences: what the equipment is, which controller exposes the
data, and where this map comes from.

## Connection
- driver: `modbus-tcp`, port: `502`, slave_id: `1`
- collect_interval: 10-60 s typical

## Address convention
App YAML addresses are 0-BASED protocol offsets with a table prefix
(`holding:<offset>`, `input:<offset>`). State explicitly which base the
SOURCE material uses and how it was converted. If the base is unverified,
show both readings and say how to verify.

## Register map
| tag | source addr | app addr | data_type | scale | unit | semantic |
|---|---|---|---|---|---|---|
| example_pressure | 40001 (1-based doc) | holding:0 | UINT16 | 0.01 | bar | pressure.discharge |

## Datapoints YAML
```yaml
- name: example_pressure
  address: "holding:0"
  data_type: UINT16
  scale: 0.01
  unit: bar
  semantic: pressure.discharge
```

## Verification & caveats
- Registers vary by firmware/configuration - verify against the device's
  own documentation before trusting live values.
- Start with demo_mode: true to validate names, units and dashboards.
