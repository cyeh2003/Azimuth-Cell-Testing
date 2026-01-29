# Battery Cell Testing

Automated electrical characterization of lithium-ion cells using a Keithley 2461 SourceMeter. This script measures Open Circuit Voltage (OCV), instantaneous resistance (R0), and DC Internal Resistance (DCIR) to enable quality control and cell matching for battery pack assembly.

## Table of Contents

- [Motivation](#motivation)
- [Tests Performed](#tests-performed)
- [Hardware Requirements](#hardware-requirements)
- [Software Setup](#software-setup)
- [Usage](#usage)
- [Configuration](#configuration)
- [Output Format](#output-format)
- [Troubleshooting](#troubleshooting)
- [References](#references)

## Motivation

Cells have varying incoming quality and we want to reject weak or bad cells before pack assembly. Mismatched cells in a pack can lead to:

- Reduced pack capacity (limited by weakest cell)
- Accelerated degradation of healthy cells
- Safety risks from cell imbalance

This script captures cell characterization data in a time-efficient, semi-automated manner. Pass/fail criteria are left to the battery pack builder based on their specific requirements.

## Tests Performed

The instrument operates in **4-wire (Kelvin) sensing mode** for accurate low-resistance measurements. If using shielded cables, connect the shield to the guard output of the instrument.

### 1. Open Circuit Voltage (OCV)

Measures the cell's equilibrium potential with zero current flow.

- **Method**: Source 0A, measure terminal voltage
- **Duration**: ~0.1 seconds
- **Purpose**: Indicates State of Charge (SOC), detects damaged cells

| OCV Range | Typical SOC (Li-ion) |
|-----------|---------------------|
| 4.2V | 100% |
| 3.7V | ~50% |
| 3.0V | ~10% |
| 2.5V | 0% (cutoff) |

### 2. Instantaneous Resistance (R0)

Measures the immediate ohmic resistance using short current pulses.

- **Method**: Apply brief current pulse (default: 1A for 2.5ms), measure voltage change
- **Duration**: ~1 second (including charge and discharge pulses)
- **Purpose**: Detects poor contacts, electrode degradation, electrolyte issues

R0 captures:
- Electrode/current collector contact resistance
- Electrolyte ionic resistance  
- Separator resistance

**Expected values for healthy 21700 cells: 20-40 mΩ**

### 3. DC Internal Resistance (DCIR)

Measures resistance including polarization effects under sustained load.

- **Method**: Apply constant current (default: 1A for 10s), measure voltage change
- **Duration**: ~25 seconds (including charge and discharge)
- **Purpose**: More representative of cell behavior during actual discharge

DCIR includes R0 plus:
- Charge transfer resistance (electrode kinetics)
- Diffusion/concentration polarization

**DCIR is typically 20-50% higher than R0**

## Hardware Requirements

| Item | Description | Example |
|------|-------------|---------|
| **SourceMeter** | Pulse-capable Keithley SMU | [Keithley 2461](https://www.tek.com/en/products/keithley/source-measure-units/2400-graphical-series-sourcemeter) |
| **Cell Holder** | 4-wire (Kelvin) battery fixture | [A2D Electronics 15A holder](https://a2delectronics.ca/shop/battery-testing/4-wire-cell-holder/) |
| **Barcode Scanner** | USB HID scanner (optional) | [Inateck Scanner](https://www.amazon.com/dp/B01M264K5L) |
| **USB Cable** | Type-B to connect SMU to computer | Included with instrument |

### Wiring Diagram

```
Keithley 2461                    Cell Holder
┌─────────────┐                  ┌─────────┐
│ HI (Force)  │──────────────────│ + Force │
│ HI (Sense)  │──────────────────│ + Sense │
│ LO (Force)  │──────────────────│ - Force │
│ LO (Sense)  │──────────────────│ - Sense │
└─────────────┘                  └─────────┘
```

## Software Setup

### Prerequisites

- Python 3.8 or higher
- USB drivers for Keithley instrument (usually automatic on modern OS)

### Installation

1. **Clone or download this repository**

2. **Create a virtual environment** (recommended):
   ```bash
   cd cell
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Verify instrument connection**:
   ```bash
   # List connected VISA instruments
   python -c "import pyvisa; print(pyvisa.ResourceManager('@py').list_resources())"
   ```

5. **Update the resource string** in `test_cells.py` if needed:
   ```python
   RESOURCE_NAME = "USB0::0x05E6::0x2461::XXXXXXXX::INSTR"  # Your instrument's address
   ```

### Verifying Setup

Test the connection before running actual tests:

```bash
python test_cells.py output.csv --test-connection
```

You should see instrument identification and hear a beep.

## Usage

### Basic Workflow

1. Ensure all cells are at **thermal steady state** in a temperature-controlled environment
2. Launch the script
3. Place a cell in the holder
4. Scan the barcode (or type serial number) when prompted
5. Wait for tests to complete (~30 seconds)
6. Remove cell and repeat

### Command Line Interface

```bash
# Basic usage - results saved to output.csv
python test_cells.py output.csv

# Use rear panel terminals
python test_cells.py output.csv --terminals rear

# Test without hardware (development/debugging)
python test_cells.py output.csv --mock

# Verify instrument connection only
python test_cells.py output.csv --test-connection

# View help
python test_cells.py --help
```

### Example Session

```
$ python test_cells.py results.csv

[INIT] Connecting to Keithley 2461...
       Resource: USB0::0x05E6::0x2461::04628946::INSTR
       Terminals: FRONT
[INIT] Instrument configured successfully
[CSV] Created new output file: results.csv

============================================================
BATTERY CELL TESTING READY
============================================================
Scan a cell barcode or type serial number to begin.
Type 'q' or press Ctrl+C to quit.

Cell serial number: CELL001

============================================================
CELL TEST: CELL001
============================================================

  [TEST 1/3] Open Circuit Voltage (OCV)
  ----------------------------------------
  Result: OCV = 3.7234 V

  [TEST 2/3] Instantaneous Resistance (R0)
  ----------------------------------------
  ...
  Results:
    R0 (average)   = 28.45 mΩ

  [TEST 3/3] DC Internal Resistance (DCIR)
  ----------------------------------------
  ...
  Results:
    DCIR (average) = 35.12 mΩ

============================================================
TEST SUMMARY
============================================================
  Serial Number : CELL001
  OCV           : 3.7234 V
  R0            : 28.45 mΩ
  DCIR          : 35.12 mΩ
============================================================

[CSV] Results saved for CELL001
Cell serial number: q

Exiting...
[SHUTDOWN] Closing instrument connection...
[SHUTDOWN] Instrument disconnected safely
```

## Configuration

Test parameters are defined as constants at the top of `test_cells.py`:

```python
# Voltage compliance limits (safety bounds)
kChargeComplianceLimit_volts = 4.2      # Max voltage during charging
kDischargeComplianceLimit_volts = 2.5   # Min voltage during discharging

# R0 test parameters
kR0PulseCurrent_amps = 1.0              # Pulse current [A]
kR0PulseDuration_seconds = 0.0025       # Pulse width [s] (2.5ms)

# DCIR test parameters  
kDcirCurrent_amps = 1.0                 # DC test current [A]
kDcirDuration_seconds = 10.0            # Current duration [s]

# Measurement settling
kVoltageSenseDwell_seconds = 0.1        # Wait before voltage read [s]
```

### Adjusting for Different Cell Types

| Cell Type | Charge Limit | Discharge Limit | Suggested Current |
|-----------|--------------|-----------------|-------------------|
| Standard Li-ion (NMC) | 4.2V | 2.5V | 1-3A |
| LiFePO4 (LFP) | 3.65V | 2.0V | 1-5A |
| High-voltage Li-ion | 4.35V | 2.5V | 1-2A |

## Output Format

Results are saved as CSV with the following columns:

| Column | Unit | Description |
|--------|------|-------------|
| Serial Number | - | Cell identifier (barcode) |
| OCV (V) | Volts | Open circuit voltage |
| R0 (Ohm) | Ohms | Average instantaneous resistance |
| R0 Charge (Ohm) | Ohms | R0 measured during charge pulse |
| R0 Discharge (Ohm) | Ohms | R0 measured during discharge pulse |
| DCIR (Ohm) | Ohms | Average DC internal resistance |
| DCIR Charge (Ohm) | Ohms | DCIR measured during charge |
| DCIR Discharge (Ohm) | Ohms | DCIR measured during discharge |

## Troubleshooting

### "No VISA resources found"

```bash
# Check if instrument is detected
python -c "import pyvisa; print(pyvisa.ResourceManager('@py').list_resources())"
```

- Verify USB cable connection
- Check instrument is powered on
- Try a different USB port
- On Linux, you may need to add udev rules for USB access

### "Settings conflict" error

This can occur if the instrument is left in an unexpected state. The script now resets the instrument before each measurement, but you can also:

```bash
# Power cycle the instrument, or
# Press the front panel "MENU" > "System" > "Reset"
```

### High resistance readings (>100mΩ)

- **Check cell holder contacts** - Clean with isopropyl alcohol
- **Verify 4-wire sensing** - All four wires must be connected
- **Check for loose connections** - Reseat all cables
- **Verify cable routing** - Keep sense wires away from noise sources

### Mock mode for development

Test the script logic without hardware:

```bash
python test_cells.py output.csv --mock
```

## References

- [Keithley 2400-series User Manual (SCPI Programming)](https://download.tek.com/manual/2400S-900-01_K-Sep2011_User.pdf)
- [Keithley 2461 Reference Manual](https://download.tek.com/manual/2461-901-01_Sept2017_Ref.pdf)
- [PyVISA Documentation](https://pyvisa.readthedocs.io/en/latest/)
- [Battery University - Internal Resistance](https://batteryuniversity.com/article/bu-902-how-to-measure-internal-resistance)
