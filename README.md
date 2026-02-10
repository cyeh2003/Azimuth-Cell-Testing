# SSCP Cell Testing

End-to-end workflow for incoming quality testing, serialization, and module grouping of lithium-ion cells for a solar car battery pack. The goal is to characterize every cell electrically, reject outliers, and group the remaining cells into parallel modules with balanced internal resistance.

## Table of Contents

- [Overview](#overview)
- [Repository Structure](#repository-structure)
- [Workflow](#workflow)
  - [Step 1 -- Serialize Cells](#step-1--serialize-cells)
  - [Step 2 -- Test Cells](#step-2--test-cells)
  - [Step 3 -- Group Cells into Modules](#step-3--group-cells-into-modules)
- [Detailed Module Reference](#detailed-module-reference)
  - [serialization/](#serialization)
  - [cell/](#cell)
  - [arrangement/](#arrangement)
- [Quick Start](#quick-start)
- [Hardware Requirements](#hardware-requirements)
- [Software Requirements](#software-requirements)

## Overview

A solar car battery pack is assembled from hundreds of individual lithium-ion cells wired in a series-parallel configuration. Cell-to-cell variation in internal resistance affects pack performance, longevity, and safety. This repository provides three tools that form a complete pipeline:

1. **Serialization** -- Generate and print QR-code labels so every cell has a unique, scannable identifier tied to its physical storage location.
2. **Cell Testing** -- Automated electrical characterization (OCV, R0, DCIR) of each cell using a Keithley 2461 SourceMeter with 4-wire Kelvin sensing.
3. **Module Arrangement** -- Algorithmic grouping of tested cells into parallel modules that minimizes resistance spread across the pack.

## Repository Structure

```
SSCP_cell_testing/
├── README.md                       # This file
├── serialization/
│   ├── README.md                   # Label printing instructions
│   ├── generate_serials.py         # Serial number generator
│   └── serial_labels.csv           # Generated label data
├── cell/
│   ├── README.md                   # Detailed testing documentation
│   ├── requirements.txt            # Python dependencies (pyvisa, etc.)
│   ├── test_cells.py               # Keithley 2461 test script
│   └── output.csv                  # Test results (one row per cell)
└── arrangement/
    ├── group_cells.py              # Module grouping algorithm
    └── modules.csv                 # Grouped output with statistics
```

## Workflow

The three steps are designed to be run in order. Each step produces a CSV that feeds into the next.

```
┌──────────────┐       ┌──────────────┐       ┌──────────────────┐
│ Serialization│       │ Cell Testing │       │ Module Grouping  │
│              │       │              │       │                  │
│ Assign IDs & │──────>│ Measure OCV, │──────>│ Balance parallel │
│ print labels │       │ R0, DCIR     │       │ resistance       │
│              │       │              │       │                  │
│ serial_labels│       │  output.csv  │       │  modules.csv     │
│     .csv     │       │              │       │                  │
└──────────────┘       └──────────────┘       └──────────────────┘
```

### Step 1 -- Serialize Cells

Generate serial numbers for your cell inventory. Serial numbers encode the physical storage location (box, row, column) so you can quickly locate any cell later.

```bash
cd serialization
python generate_serials.py > serial_labels.csv
```

The default configuration generates serials for 3 boxes x 10 rows x 13 columns = **390 cells**. Edit `generate_serials.py` to match your inventory layout.

Print the labels and affix one to each cell before testing. See `serialization/README.md` for label printer setup (Brother QL-series).

### Step 2 -- Test Cells

Run automated electrical characterization on every labeled cell. The script drives a Keithley 2461 SourceMeter to measure:

| Test | What It Measures | Method | Duration |
|------|-----------------|--------|----------|
| **OCV** | Open Circuit Voltage | Source 0A, measure voltage | ~0.1s |
| **R0** | Instantaneous resistance | 1A pulse for 2.5ms | ~1s |
| **DCIR** | DC Internal Resistance | 1A for 10s (charge + discharge) | ~15s |

```bash
cd cell
pip install -r requirements.txt
python test_cells.py output.csv
```

The script prompts you to scan (or type) each cell's serial number, runs all three tests, and appends the results to the CSV. A complete session for one cell takes about 30 seconds.

**Output columns** (`output.csv`):

| Column | Unit | Description |
|--------|------|-------------|
| Serial Number | -- | Integer cell identifier |
| OCV (V) | Volts | Open circuit voltage |
| R0 (Ohm) | Ohms | Average instantaneous resistance |
| R0 Charge (Ohm) | Ohms | R0 from charge pulse |
| R0 Discharge (Ohm) | Ohms | R0 from discharge pulse |
| DCIR (Ohm) | Ohms | Average DC internal resistance |
| DCIR Charge (Ohm) | Ohms | DCIR from charge phase |
| DCIR Discharge (Ohm) | Ohms | DCIR from discharge phase |

See `cell/README.md` for full hardware setup, wiring diagrams, configuration, and troubleshooting.

### Step 3 -- Group Cells into Modules

Once all cells are tested, run the grouping algorithm to assign cells to modules with balanced parallel resistance.

```bash
cd arrangement
python group_cells.py \
  --input ../cell/output.csv \
  --series 20 \
  --parallel 15 \
  --output modules.csv
```

| Argument | Required | Description |
|----------|----------|-------------|
| `--input` | Yes | Path to the test results CSV |
| `--series` | Yes | Number of modules (series groups) in the pack |
| `--parallel` | Yes | Number of cells wired in parallel per module |
| `--output` | No | Output file path (default: `modules.csv`) |

Adjust `--series` and `--parallel` to match your pack configuration. The total cells needed is `series x parallel`; if your CSV has more cells than needed, the algorithm automatically excludes the highest and lowest DCIR outliers.

## Detailed Module Reference

### serialization/

**`generate_serials.py`** -- A short script that generates a CSV of serial numbers. Each serial encodes `{box}{row}{column}`, e.g. `1A01` means box 1, row A, column 1. The output is designed to be fed directly into label-printing software (Brother P-Touch Editor or similar).

**`serial_labels.csv`** -- The generated label data with columns: `Count`, `Box`, `Row`, `Column`, `Serial`.

### cell/

**`test_cells.py`** (~1000 lines) -- Full instrument driver and test orchestration script. Key features:

- **`Keithley2461` class**: VISA-based instrument driver that handles connection, configuration, sourcing current, and reading voltage. Supports both front and rear panel terminals.
- **Mock mode** (`--mock`): Simulates instrument responses with realistic random values for development and debugging without hardware.
- **4-wire Kelvin sensing**: All resistance measurements use separate force and sense leads for accuracy down to sub-milliohm levels.
- **Duplicate detection**: If a serial number already exists in the output CSV, the script offers to retest and replace the old data.
- **Safety limits**: Configurable voltage compliance bounds (default 2.5V--4.2V) prevent over-charge or over-discharge.

**Test parameters** (configurable constants at top of file):

```
Charge compliance limit:   4.2 V
Discharge compliance limit: 2.5 V
R0 pulse current:          1.0 A
R0 pulse duration:         2.5 ms
DCIR current:              1.0 A
DCIR duration:             10.0 s
Voltage sense dwell:       0.1 s
```

**`requirements.txt`**:
```
pyvisa
pyvisa-py
pyserial
pyusb
```

**`output.csv`** -- Test results, one row per cell. This is the input to the grouping algorithm.

### arrangement/

**`group_cells.py`** (~226 lines) -- Module grouping algorithm. The pipeline:

1. **Read**: Parse the test CSV, extracting serial number, OCV, and DCIR for each cell.
2. **Filter**: Sort all cells by DCIR and select the middle chunk, symmetrically trimming the highest and lowest outliers until exactly `series x parallel` cells remain.
3. **Group (Greedy Best-Fit)**: Sort the selected cells by conductance (1/DCIR) in descending order. For each cell, assign it to the non-full module with the lowest total conductance. This balances the parallel resistance across all modules.
4. **Output**: Write a structured CSV and print statistics to the console.

**`modules.csv`** -- The grouped output. The CSV is organized into several sections for clarity:

- **Per-module blocks**: Each module gets a header row (module number, cell count, parallel DCIR), followed by its cells sorted by serial number with their DCIR and OCV values. A blank row separates each module.
- **Module summary table**: A compact table listing every module on one row with its parallel DCIR, cell count, and comma-separated list of serial numbers for quick lookup.
- **Statistics**: Min, max, and average parallel DCIR across all modules, plus the absolute and percentage spread.
- **Excluded cells**: Lists every cell that was cut as an outlier, sorted by serial number, with DCIR, OCV, and reason.

Example output structure:
```
--- Module 1 ---,Cells: 9,Parallel DCIR: 0.003596 Ohm
Serial Number,DCIR (Ohm),OCV (V)
23,0.034047,3.452216
37,0.033506,3.452523
...

--- Module 2 ---,Cells: 9,Parallel DCIR: 0.003595 Ohm
Serial Number,DCIR (Ohm),OCV (V)
29,0.033762,3.452344
...

=== Module Summary ===
Module,Parallel DCIR (Ohm),Cell Count,Serial Numbers
Module 1,0.003596,9,"23, 37, 82, 85, 122, 177, 200, 252, 269"
Module 2,0.003595,9,"29, 33, 76, 93, 102, 186, 188, 196, 209"
...

=== Statistics ===
Metric,Value
Min Parallel DCIR,0.003594 Ohm
Max Parallel DCIR,0.003598 Ohm
Avg Parallel DCIR,0.003596 Ohm
Spread,0.000004 Ohm (0.1234%)

=== Excluded Cells (30) ===
Serial Number,DCIR (Ohm),OCV (V),Reason
120,0.031927,3.452710,Outlier
...
```

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url> && cd SSCP_cell_testing

# 2. Set up Python environment
cd cell
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. (Optional) Generate serial labels
cd ../serialization
python generate_serials.py > serial_labels.csv

# 4. Test cells (use --mock if you don't have the instrument)
cd ../cell
python test_cells.py output.csv --mock

# 5. Group cells into modules
cd ../arrangement
python group_cells.py \
  --input ../cell/output.csv \
  --series 20 \
  --parallel 15 \
  --output modules.csv
```

## Hardware Requirements

| Item | Description | Example |
|------|-------------|---------|
| **SourceMeter** | Pulse-capable Keithley SMU | [Keithley 2461](https://www.tek.com/en/products/keithley/source-measure-units/2400-graphical-series-sourcemeter) |
| **Cell Holder** | 4-wire (Kelvin) battery fixture | [A2D Electronics 15A holder](https://a2delectronics.ca/shop/battery-testing/4-wire-cell-holder/) |
| **Barcode Scanner** | USB HID scanner (optional) | [Inateck Scanner](https://www.amazon.com/dp/B01M264K5L) |
| **Label Printer** | For serial number QR codes (optional) | [Brother QL820NWBC](https://www.brother-usa.com/products/ql820nwbc) |
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

## Software Requirements

- Python 3.8+
- No hardware needed for development -- use `--mock` mode for testing and `--test-connection` to verify instrument communication
- Dependencies are listed in `cell/requirements.txt` (`pyvisa`, `pyvisa-py`, `pyserial`, `pyusb`)
- The grouping script (`arrangement/group_cells.py`) uses only the Python standard library
