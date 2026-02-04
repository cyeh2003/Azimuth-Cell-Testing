#!/usr/bin/env python3
"""
Battery Cell Testing Script for Keithley 2461 Source Measure Unit.

This script performs automated electrical characterization of lithium-ion cells,
measuring Open Circuit Voltage (OCV), instantaneous resistance (R0), and DC
Internal Resistance (DCIR). Results are logged to a CSV file for quality control
and cell matching purposes.

Tests Performed:
    1. OCV  - Open Circuit Voltage measurement at zero current
    2. R0   - Instantaneous resistance via short current pulses (charge + discharge)
    3. DCIR - DC Internal Resistance via longer duration current application

Hardware Requirements:
    - Keithley 2461 SourceMeter (or compatible 2400-series SMU)
    - 4-wire (Kelvin) cell holder for accurate measurements
    - USB connection to the instrument

Usage:
    python test_cells.py output.csv --terminals front
    python test_cells.py output.csv --mock  # For testing without hardware
"""

import argparse
import csv
import time
import sys
import string

# =============================================================================
# Dependency Validation
# =============================================================================
# Check for required packages before proceeding. This provides a clear error
# message if dependencies are missing, rather than failing mid-execution.

try:
    import pyvisa
except ImportError:
    print("\n" + "=" * 60)
    print("ERROR: Missing required dependency 'pyvisa'")
    print("=" * 60)
    print("\nInstall it using:")
    print("    pip install pyvisa pyvisa-py")
    print("\nFor USB support, you may also need:")
    print("    pip install pyusb")
    print("=" * 60)
    sys.exit(1)

# =============================================================================
# Instrument Configuration
# =============================================================================
# VISA resource string for the Keithley 2461. Update this to match your
# instrument's address. Use `pyvisa.ResourceManager().list_resources()` to
# discover connected instruments.

RESOURCE_NAME = "USBn::0x5E6::0x2461::04628946::INSTR"

# =============================================================================
# Test Parameters
# =============================================================================
# These constants define the electrical limits and test conditions. Adjust
# based on your cell specifications (e.g., Samsung 21700-50S: 2.5V-4.2V).

# Voltage compliance limits (safety bounds)
kChargeComplianceLimit_volts = 4.2      # Maximum voltage during charging
kDischargeComplianceLimit_volts = 2.5   # Minimum voltage during discharging

# R0 (instantaneous resistance) test parameters
kR0PulseCurrent_amps = 1.0              # Pulse current magnitude [A]
kR0PulseDuration_seconds = 0.0025       # Pulse width [s] (2.5ms)

# DCIR (DC internal resistance) test parameters
kDcirCurrent_amps = 1                   # DC test current magnitude [A]
kDcirDuration_seconds = 5.0             # Current application duration [s]

# Measurement settling time
kVoltageSenseDwell_seconds = 0.1        # Wait time before voltage reading [s]


class Keithley2461:
    """
    Driver class for Keithley 2461 SourceMeter Unit.
    
    Provides high-level methods for battery cell testing including voltage/current
    measurement, DC sourcing, and pulsed current operations. Supports both real
    hardware and mock mode for development/testing.
    
    Attributes:
        mock (bool): If True, simulates instrument responses without hardware.
        inst: PyVISA instrument resource (None if mock=True).
    
    Example:
        >>> smu = Keithley2461("USB0::0x05E6::0x2461::04628946::INSTR")
        >>> smu.test_connection()
        >>> voltage = smu.measure_voltage()
        >>> smu.close()
    """
    
    def __init__(self, resource_name: str, mock: bool = False, terminals: str = 'front'):
        """
        Initialize connection to the Keithley 2461.
        
        Args:
            resource_name: VISA resource string (e.g., "USB0::0x05E6::...::INSTR")
            mock: If True, operate in simulation mode without hardware
            terminals: Terminal selection - 'front' or 'rear' panel connections
        
        Raises:
            pyvisa.errors.VisaIOError: If connection to instrument fails
        """
        self.mock = mock
        self.inst = None
        
        if self.mock:
            print(f"[MOCK MODE] Simulating connection to {resource_name}")
            return
        
        print(f"[INIT] Connecting to Keithley 2461...")
        print(f"       Resource: {RESOURCE_NAME}")
        
        # Initialize PyVISA with the pure-Python backend (works without NI-VISA)
        rm = pyvisa.ResourceManager('@py')
        self.inst = rm.open_resource(RESOURCE_NAME)
        
        # Configure serial communication parameters
        self.inst.timeout = 5000          # 5 second timeout for commands
        self.inst.write_termination = '\n'
        self.inst.read_termination = '\n'
        
        # Reset instrument to known state and clear any pending errors
        self.inst.write("*RST")
        self.inst.write("*CLS")
        
        # Enable 4-wire (Kelvin) sensing for accurate low-resistance measurements
        # This eliminates lead resistance from the measurement
        self.inst.write(":SENS:VOLT:RSEN ON")
        
        # Select physical terminal connection (front or rear panel)
        terminal_cmd = "REAR" if terminals.lower() == 'rear' else "FRONT"
        self.inst.write(f":ROUTe:TERMinals {terminal_cmd}")
        print(f"       Terminals: {terminal_cmd}")
        
        # Configure as current source with voltage measurement
        self.inst.write(":SOURce:FUNCtion CURRent")
        
        # Enable auto-ranging for flexibility across different cell types
        self.inst.write(":SOURce:CURR:RANGe:AUTO ON")
        self.inst.write(":SENS:VOLT:RANGe:AUTO ON")
        self.inst.write(":SENS:CURR:RANGe:AUTO ON")
        
        # Enable output (required for 4-wire sensing to function)
        self.inst.write(":OUTPut:STATe ON")
        
        print("[INIT] Instrument configured successfully")

    @staticmethod
    def _clean_string(input_string: str) -> str:
        """
        Remove non-printable characters from instrument response strings.
        
        Some instruments may include control characters or binary data in
        responses. This ensures we only process valid ASCII text.
        
        Args:
            input_string: Raw string from instrument query
            
        Returns:
            String containing only printable ASCII characters
        """
        return "".join(char for char in input_string if char in string.printable)

    @staticmethod
    def _parse_reading(input_string: str) -> dict:
        """
        Parse a comma-separated measurement response into a structured dict.
        
        The Keithley returns readings in the format:
        voltage, current, resistance, timestamp, status
        
        Args:
            input_string: Raw comma-separated response from :MEAS? query
            
        Returns:
            Dictionary with keys: voltage, current, resistance, time, status
            
        Raises:
            ValueError: If response cannot be parsed (wrong format/field count)
        """
        cleaned = Keithley2461._clean_string(input_string)
        fields = cleaned.split(',')
        
        if len(fields) < 5:
            raise ValueError(
                f"Invalid measurement response: expected 5 fields, got {len(fields)}. "
                f"Raw response: {input_string!r}"
            )
        
        return {
            'voltage': float(fields[0]),
            'current': float(fields[1]),
            'resistance': float(fields[2]),
            'time': float(fields[3]),
            'status': float(fields[4])
        }

    def close(self):
        """
        Safely disconnect from the instrument.
        
        Turns off the output and closes the VISA session. Always call this
        when finished to leave the instrument in a safe state.
        """
        if self.mock:
            print("[MOCK MODE] Connection closed")
            return
            
        print("[SHUTDOWN] Closing instrument connection...")
        self.inst.write(":OUTP OFF")
        self.inst.close()
        print("[SHUTDOWN] Instrument disconnected safely")
            
    def reset(self):
        """Reset instrument to factory default state."""
        if not self.mock:
            self.inst.write("*RST")

    def output_on(self):
        """Enable the source output."""
        if not self.mock:
            self.inst.write(":OUTP ON")

    def output_off(self):
        """Disable the source output (safe state)."""
        if not self.mock:
            self.inst.write(":OUTP OFF")
    
    def beep_success(self):
        """
        Play a two-tone success beep on the instrument.
        
        Provides audible feedback when a test completes successfully,
        useful in production environments.
        """
        if self.mock:
            return
            
        # Two-tone ascending beep: 1400Hz then 2000Hz
        self.inst.write("SYST:BEEP:IMM 1400, 0.1")
        time.sleep(0.1)
        self.inst.write("SYST:BEEP:IMM 2000, 0.05")
        time.sleep(0.05)

    def measure_voltage(self) -> float:
        """
        Measure the voltage at the cell terminals.
        
        Uses 4-wire sensing if configured during initialization.
        Output must be enabled for accurate 4-wire measurements.
        
        Returns:
            Measured voltage in volts
        """
        if self.mock:
            return 3.7  # Typical Li-ion nominal voltage
        
        self.inst.write(':SENS:FUNC "VOLT"')
        voltage_reading = self.inst.query(":READ?")
        voltage_value = float(voltage_reading.strip())
        return voltage_value

    def measure_current(self) -> float:
        """
        Measure the current flowing through the cell.
        
        Returns:
            Measured current in amperes
        """
        if self.mock:
            return 0.0
            
        self.inst.write(":SOUR:FUNC:SHAP DC")
        return self._parse_reading(self.inst.query(":MEAS:CURR?"))['current']

    def source_current(self, current: float, voltage_limit: float):
        """
        Configure the SMU to source a constant DC current.
        
        Sets up the instrument in current-source mode with voltage compliance.
        The compliance limit protects the cell from over/under voltage.
        
        Args:
            current: Target current in amperes (positive=charge, negative=discharge)
            voltage_limit: Voltage compliance limit in volts
        """
        if self.mock:
            return
        
        # Reset to clear any previous digitize/pulse mode configuration
        self.inst.write("*RST")
        
        # Re-enable 4-wire sensing (reset disables it)
        self.inst.write(":SENS:VOLT:RSEN ON")
        
        # Configure as current source measuring voltage
        self.inst.write(":SENS:FUNC 'VOLT'")
        self.inst.write(":SOUR:FUNC CURR")
        self.inst.write(":SOUR:CURR:RANG:AUTO ON")
        self.inst.write(f":SOUR:CURR:LEV {current}")
        self.inst.write(f":SOUR:CURR:VLIM {voltage_limit}")

    def source_voltage(self, voltage: float, current_limit: float):
        """
        Configure the SMU to source a constant DC voltage.
        
        Sets up the instrument in voltage-source mode with current compliance.
        
        Args:
            voltage: Target voltage in volts
            current_limit: Current compliance limit in amperes
        """
        if self.mock:
            return
            
        self.inst.write(":SOUR:FUNC:SHAP DC")
        self.inst.write(":SOUR:FUNC VOLT")
        self.inst.write(f":SOUR:VOLT {voltage}")
        self.inst.write(f":SENS:CURR:PROT {current_limit}")

    def source_pulse_current(self, current: float, voltage_limit: float, 
                             width: float, delay: float = 0) -> float:
        """
        Execute a high-speed current pulse and capture voltage during the pulse.
        
        This method uses the Keithley's digitizer to sample voltage at 500kS/s
        during a current pulse. The returned voltage is the average of the
        central 50% of samples (avoiding edge transients).
        
        This is essential for accurate R0 measurements where the pulse must be
        short enough to avoid thermal and electrochemical effects.
        
        Args:
            current: Pulse current in amperes (positive=charge, negative=discharge)
            voltage_limit: Voltage compliance limit in volts
            width: Pulse duration in seconds (e.g., 0.0025 for 2.5ms)
            delay: Optional delay before pulse starts, in seconds
            
        Returns:
            Average voltage during pulse plateau (central 50% of samples)
            
        Raises:
            RuntimeError: If digitized data cannot be captured or parsed
        """
        if self.mock:
            # Simulate voltage change under load based on ~25mΩ internal resistance
            return 3.8 if current > 0 else 3.6

        inst = self.inst

        # Configure source function for current output with readback
        inst.write(":SOURce:FUNC CURRent")
        inst.write(":SOURce:CURRent:READ:BACK ON")

        # Configure digitizer for high-speed voltage acquisition
        # 500kS/s sample rate captures fast transients during the pulse
        inst.write(':DIGitize:FUNC "VOLTage"')
        inst.write(":DIGitize:VOLTage:RSENse ON")   # Use 4-wire sensing
        inst.write(":DIGitize:VOLTage:RANGe 10")    # 10V range for Li-ion
        inst.write(":DIGitize:VOLTage:SRATe 500000") # 500kS/s sample rate

        # Allocate buffer for digitized samples
        inst.write(':TRACe:POINTS 100000, "defbuffer1"')

        # Build pulse train command
        # Format: bias, level, width, count, measure, buffer, delay, off_time, 
        #         bias_limit, pulse_limit, fail_abort
        bias_level = 0.0
        pulse_level = float(current)
        pulse_width = float(width)
        count = 1  # Single pulse
        measure_enable = 1  # Enable digitizer during pulse
        start_delay = max(0.0, float(delay))
        off_time = max(0.01, 10.0 * pulse_width)  # Off time after pulse
        x_bias_limit = float(voltage_limit)
        x_pulse_limit = float(voltage_limit)

        cmd = (
            f":SOURce:PULSe:TRain:CURRent "
            f"{bias_level}, {pulse_level}, {pulse_width}, "
            f"{count}, {measure_enable}, \"defbuffer1\", "
            f"{start_delay}, {off_time}, "
            f"{x_bias_limit}, {x_pulse_limit}, 0"
        )
        inst.write(cmd)
        
        # Calculate expected sample count: 500kS/s × pulse_width + margin
        sample_rate = 500000
        expected_samples = int(sample_rate * pulse_width) + 100

        # Execute the pulse sequence
        inst.write(":INIT")
        
        # Wait for pulse to complete (with safety margin)
        total_time = start_delay + pulse_width + off_time + 0.5
        time.sleep(total_time)

        # Retrieve digitized voltage samples from buffer
        inst.write(f':TRACe:DATA? 1, {expected_samples}, "defbuffer1", READ')
        raw = inst.read_raw().decode('ascii').strip()
       
        try:
            samples = [float(s) for s in raw.strip().split(",") if s.strip()]
        except ValueError as e:
            raise RuntimeError(
                f"Failed to parse digitized voltage data from instrument. "
                f"Raw response: {raw!r}. Error: {e}"
            )

        if not samples:
            raise RuntimeError(
                "No voltage samples captured during pulse. "
                "Check instrument connections and trigger configuration."
            )

        # Extract the central 50% of samples as the pulse plateau
        # This avoids transients at pulse edges (rise/fall times)
        n = len(samples)
        start_idx = n // 4
        end_idx = max(start_idx + 1, (3 * n) // 4)
        plateau = samples[start_idx:end_idx]

        avg_voltage = sum(plateau) / len(plateau)
        return avg_voltage

    def test_connection(self) -> bool:
        """
        Verify communication with the instrument.
        
        Queries the instrument identification and plays a success beep.
        Use this to validate the setup before running tests.
        
        Returns:
            True if connection is successful, False otherwise
        """
        if self.mock:
            print("[MOCK MODE] Connection test: PASSED")
            return True
        
        try:
            idn = self.inst.query("*IDN?")
            self.beep_success()
            
            idn_parts = idn.strip().split(',')
            print("\n" + "=" * 50)
            print("CONNECTION TEST: PASSED")
            print("=" * 50)
            
            if len(idn_parts) >= 4:
                print(f"  Manufacturer : {idn_parts[0]}")
                print(f"  Model        : {idn_parts[1]}")
                print(f"  Serial       : {idn_parts[2]}")
                print(f"  Firmware     : {idn_parts[3]}")
            else:
                print(f"  Instrument ID: {idn.strip()}")
                
            print("=" * 50 + "\n")
            return True
            
        except Exception as e:
            print("\n" + "=" * 50)
            print("CONNECTION TEST: FAILED")
            print("=" * 50)
            print(f"  Error: {e}")
            print("\nTroubleshooting:")
            print("  1. Verify USB cable connection")
            print("  2. Check instrument power")
            print("  3. Confirm RESOURCE_NAME matches your instrument")
            print("  4. Try: pyvisa.ResourceManager('@py').list_resources()")
            print("=" * 50 + "\n")
            return False


# =============================================================================
# CSV Helper Functions
# =============================================================================

def check_duplicate_serial(csv_path: str, serial_number: str) -> dict | None:
    """
    Check if a serial number already exists in the CSV file.
    
    Args:
        csv_path: Path to the CSV file
        serial_number: Serial number to check for
        
    Returns:
        The existing row as a dictionary if found, None otherwise
    """
    try:
        with open(csv_path, 'r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row.get("Serial Number") == serial_number:
                    return row
    except FileNotFoundError:
        pass  # File doesn't exist yet, no duplicates possible
    
    return None


def remove_serial_from_csv(csv_path: str, serial_number: str, fieldnames: list):
    """
    Remove an entry with the given serial number from the CSV file.
    
    Reads all rows, filters out the matching serial number, and rewrites the file.
    
    Args:
        csv_path: Path to the CSV file
        serial_number: Serial number to remove
        fieldnames: List of CSV column names for rewriting
    """
    rows_to_keep = []
    
    try:
        with open(csv_path, 'r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row.get("Serial Number") != serial_number:
                    rows_to_keep.append(row)
    except FileNotFoundError:
        return  # Nothing to remove
    
    # Rewrite the file without the removed entry
    with open(csv_path, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_to_keep)
    
    print(f"[CSV] Removed previous entry for {serial_number}")


def prompt_duplicate_action(serial_number: str, existing_data: dict) -> str:
    """
    Prompt the user for action when a duplicate serial number is detected.
    
    Args:
        serial_number: The duplicate serial number
        existing_data: The existing row data from the CSV
        
    Returns:
        User's choice: 'retest', 'skip', or 'rename'
    """
    print("\n" + "-" * 60)
    print(f"DUPLICATE DETECTED: {serial_number}")
    print("-" * 60)
    print("\nThis cell already has test results in the output file:")
    print(f"  OCV  : {float(existing_data.get('OCV (V)', 0)):.4f} V")
    print(f"  R0   : {float(existing_data.get('R0 (Ohm)', 0))*1000:.2f} mΩ")
    print(f"  DCIR : {float(existing_data.get('DCIR (Ohm)', 0))*1000:.2f} mΩ")
    print("\nOptions:")
    print("  [R] Retest - Test it again! This will OVERWRITE the previous results")
    print("  [S] Skip   - Cancel and enter a different serial number")
    print("  [N] New    - This is a DIFFERENT cell, enter a new serial number")
    
    while True:
        choice = input("\nYour choice (R/S/N): ").strip().upper()
        
        if choice in ('R', 'RETEST'):
            return 'retest'
        elif choice in ('S', 'SKIP'):
            return 'skip'
        elif choice in ('N', 'NEW'):
            return 'rename'
        else:
            print("  Invalid choice. Please enter R, S, or N.")


# =============================================================================
# Individual Test Functions
# =============================================================================

def test_ocv(inst: Keithley2461) -> float:
    """
    Measure the Open Circuit Voltage (OCV) of the cell.
    
    OCV is measured with zero source current, representing the cell's
    equilibrium potential. This is a fundamental indicator of State of Charge.
    
    Args:
        inst: Initialized Keithley2461 instance
        
    Returns:
        Open circuit voltage in volts
    """
    print("\n  [TEST 1/3] Open Circuit Voltage (OCV)")
    print("  " + "-" * 40)
    
    # Configure for zero-current voltage measurement
    inst.source_current(0.0, kChargeComplianceLimit_volts)
    inst.output_on()
    
    # Allow settling time for stable reading
    time.sleep(kVoltageSenseDwell_seconds)
    
    ocv = inst.measure_voltage()
    inst.output_off()
    
    print(f"  Result: OCV = {ocv:.4f} V")
    
    # Validate OCV is within expected Li-ion range
    if ocv < 2.0 or ocv > 4.5:
        print(f"  WARNING: OCV ({ocv:.2f}V) outside typical Li-ion range (2.0-4.5V)")
    
    return ocv


def test_r0(inst: Keithley2461) -> dict:
    """
    Measure instantaneous resistance (R0) via pulse testing.
    
    R0 represents the immediate ohmic resistance of the cell, including:
    - Electrode/collector contact resistance
    - Electrolyte ionic resistance
    - Separator resistance
    
    Method:
        1. Measure idle voltage (V_idle)
        2. Apply short current pulse and capture voltage (V_load)
        3. Calculate R = ΔV / ΔI
        4. Repeat for both charge and discharge directions
        5. Average the two values for R0 estimate
    
    Args:
        inst: Initialized Keithley2461 instance
        
    Returns:
        Dictionary containing:
            - r0: Average R0 (charge + discharge) in ohms
            - r0_charge: Charging direction R0 in ohms
            - r0_discharge: Discharging direction R0 in ohms
    """
    print(f"\n  [TEST 2/3] Instantaneous Resistance (R0)")
    print("  " + "-" * 40)
    print(f"  Parameters: {kR0PulseCurrent_amps}A pulse, {kR0PulseDuration_seconds*1000:.1f}ms width")
    
    # --- Charge Direction ---
    print("  \n  Charge direction:")
    
    # Measure idle voltage before charge pulse
    inst.source_current(0.0, kChargeComplianceLimit_volts)
    inst.output_on()
    time.sleep(kVoltageSenseDwell_seconds)
    v_idle_charge = inst.measure_voltage()
    inst.output_off()
    print(f"    V_idle (pre-charge)  = {v_idle_charge:.4f} V")
    
    # Execute charge pulse and capture voltage
    v_load_charge = inst.source_pulse_current(
        kR0PulseCurrent_amps, 
        kChargeComplianceLimit_volts, 
        kR0PulseDuration_seconds
    )
    print(f"    V_load (during pulse) = {v_load_charge:.4f} V")
    
    # --- Discharge Direction ---
    print("  \n  Discharge direction:")
    
    # Measure idle voltage before discharge pulse
    inst.source_current(0.0, kDischargeComplianceLimit_volts)
    inst.output_on()
    time.sleep(kVoltageSenseDwell_seconds)
    v_idle_discharge = inst.measure_voltage()
    inst.output_off()
    print(f"    V_idle (pre-discharge) = {v_idle_discharge:.4f} V")
    
    # Execute discharge pulse and capture voltage
    v_load_discharge = inst.source_pulse_current(
        -kR0PulseCurrent_amps,  # Negative for discharge
        kDischargeComplianceLimit_volts, 
        kR0PulseDuration_seconds
    )
    print(f"    V_load (during pulse) = {v_load_discharge:.4f} V")
    
    # --- Calculate R0 ---
    # R = ΔV / ΔI (using absolute current magnitude for both)
    r_charge = (v_load_charge - v_idle_charge) / kR0PulseCurrent_amps
    r_discharge = (v_idle_discharge - v_load_discharge) / kR0PulseCurrent_amps
    r0 = (r_charge + r_discharge) / 2.0
    
    print(f"\n  Results:")
    print(f"    R0 (charge)    = {r_charge*1000:.2f} mΩ")
    print(f"    R0 (discharge) = {r_discharge*1000:.2f} mΩ")
    print(f"    R0 (average)   = {r0*1000:.2f} mΩ")
    
    # Validate R0 is within expected range for 21700 cells (~20-40mΩ)
    if r0 > 0.1:  # 100mΩ threshold
        print(f"  WARNING: R0 ({r0*1000:.1f}mΩ) seems high. Check cell contacts.")
    
    return {
        'r0': r0,
        'r0_charge': r_charge,
        'r0_discharge': r_discharge
    }


def test_dcir(inst: Keithley2461) -> dict:
    """
    Measure DC Internal Resistance (DCIR) via sustained current application.
    
    DCIR includes R0 plus additional polarization effects that develop over
    time under load:
    - Charge transfer resistance (electrode kinetics)
    - Diffusion/concentration polarization
    
    DCIR is typically larger than R0 and more representative of cell behavior
    during sustained discharge.
    
    Method:
        1. Measure idle voltage
        2. Apply constant current for duration (e.g., 10 seconds)
        3. Measure voltage under load
        4. Calculate R = ΔV / ΔI
        5. Repeat for charge and discharge directions
    
    Args:
        inst: Initialized Keithley2461 instance
        
    Returns:
        Dictionary containing:
            - dcir: Average DCIR (charge + discharge) in ohms
            - dcir_charge: Charging direction DCIR in ohms
            - dcir_discharge: Discharging direction DCIR in ohms
    """
    print(f"\n  [TEST 3/3] DC Internal Resistance (DCIR)")
    print("  " + "-" * 40)
    print(f"  Parameters: {kDcirCurrent_amps}A for {kDcirDuration_seconds}s")
    
    # --- Charge Direction ---
    print("\n  Charge direction:")
    
    # Measure idle voltage before charge
    inst.source_current(0.0, kChargeComplianceLimit_volts)
    inst.output_on()
    time.sleep(kVoltageSenseDwell_seconds)
    v_idle_charge = inst.measure_voltage()
    inst.output_off()
    print(f"    V_idle (pre-charge) = {v_idle_charge:.4f} V")
    
    # Apply charge current for specified duration
    print(f"    Applying {kDcirCurrent_amps}A for {kDcirDuration_seconds}s...")
    inst.source_current(kDcirCurrent_amps, kChargeComplianceLimit_volts)
    inst.output_on()
    time.sleep(kDcirDuration_seconds)
    v_load_charge = inst.measure_voltage()
    inst.output_off()
    print(f"    V_load (end of charge) = {v_load_charge:.4f} V")
    
    # --- Discharge Direction ---
    print("\n  Discharge direction:")
    
    # Measure idle voltage before discharge
    inst.source_current(0.0, kDischargeComplianceLimit_volts)
    inst.output_on()
    time.sleep(kVoltageSenseDwell_seconds)
    v_idle_discharge = inst.measure_voltage()
    inst.output_off()
    print(f"    V_idle (pre-discharge) = {v_idle_discharge:.4f} V")
    
    # Apply discharge current for specified duration
    print(f"    Applying {-kDcirCurrent_amps}A for {kDcirDuration_seconds}s...")
    inst.source_current(-kDcirCurrent_amps, kDischargeComplianceLimit_volts)
    inst.output_on()
    time.sleep(kDcirDuration_seconds)
    v_load_discharge = inst.measure_voltage()
    inst.output_off()
    print(f"    V_load (end of discharge) = {v_load_discharge:.4f} V")
    
    # --- Calculate DCIR ---
    r_charge = (v_load_charge - v_idle_charge) / kDcirCurrent_amps
    r_discharge = (v_idle_discharge - v_load_discharge) / kDcirCurrent_amps
    dcir = (r_charge + r_discharge) / 2.0
    
    print(f"\n  Results:")
    print(f"    DCIR (charge)    = {r_charge*1000:.2f} mΩ")
    print(f"    DCIR (discharge) = {r_discharge*1000:.2f} mΩ")
    print(f"    DCIR (average)   = {dcir*1000:.2f} mΩ")
    
    return {
        'dcir': dcir,
        'dcir_charge': r_charge,
        'dcir_discharge': r_discharge
    }


def run_tests(inst: Keithley2461, serial_number: str) -> dict:
    """
    Execute the complete battery cell test sequence.
    
    Runs all three tests (OCV, R0, DCIR) in sequence and aggregates results
    into a dictionary suitable for CSV logging.
    
    Args:
        inst: Initialized Keithley2461 instance
        serial_number: Cell identification string (e.g., barcode)
        
    Returns:
        Dictionary with all test results, keyed for CSV fieldnames
    """
    print("\n" + "=" * 60)
    print(f"CELL TEST: {serial_number}")
    print("=" * 60)
    
    # Execute test sequence
    ocv = test_ocv(inst)
    r0_results = test_r0(inst)
    dcir_results = test_dcir(inst)
    
    # Aggregate results
    results = {
        "Serial Number": serial_number,
        "OCV (V)": ocv,
        "R0 (Ohm)": r0_results['r0'],
        "R0 Charge (Ohm)": r0_results['r0_charge'],
        "R0 Discharge (Ohm)": r0_results['r0_discharge'],
        "DCIR (Ohm)": dcir_results['dcir'],
        "DCIR Charge (Ohm)": dcir_results['dcir_charge'],
        "DCIR Discharge (Ohm)": dcir_results['dcir_discharge']
    }
    
    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"  Serial Number : {serial_number}")
    print(f"  OCV           : {ocv:.4f} V")
    print(f"  R0            : {r0_results['r0']*1000:.2f} mΩ")
    print(f"  DCIR          : {dcir_results['dcir']*1000:.2f} mΩ")
    print("=" * 60 + "\n")
    
    return results


def main():
    """
    Main entry point for the battery cell testing script.
    
    Parses command-line arguments, initializes the instrument, and runs an
    interactive loop prompting for cell serial numbers and executing tests.
    """
    parser = argparse.ArgumentParser(
        description="Battery Cell Testing Script for Keithley 2461",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
            Examples:
            python test_cells.py output.csv                    # Basic usage
            python test_cells.py output.csv --terminals rear   # Use rear terminals
            python test_cells.py output.csv --mock             # Test without hardware
            python test_cells.py output.csv --test-connection  # Verify instrument connection
        """
    )
    parser.add_argument(
        "output_csv", 
        help="Path to the output CSV file for test results"
    )
    parser.add_argument(
        "--resource", 
        default=RESOURCE_NAME,
        help=f"VISA resource string (default: {RESOURCE_NAME})"
    )
    parser.add_argument(
        "--mock", 
        action="store_true", 
        help="Run in mock mode without hardware (for testing/development)"
    )
    parser.add_argument(
        "--terminals", 
        choices=['front', 'rear'], 
        default='front',
        help="Select front or rear panel terminals (default: front)"
    )
    parser.add_argument(
        "--test-connection", 
        action="store_true",
        help="Test instrument connection and exit"
    )
    args = parser.parse_args()

    # Define CSV column structure
    fieldnames = [
        "Serial Number", 
        "OCV (V)", 
        "R0 (Ohm)", 
        "R0 Charge (Ohm)", 
        "R0 Discharge (Ohm)", 
        "DCIR (Ohm)", 
        "DCIR Charge (Ohm)", 
        "DCIR Discharge (Ohm)"
    ]
    
    # Create CSV file with header if it doesn't exist
    try:
        with open(args.output_csv, 'x', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            print(f"[CSV] Created new output file: {args.output_csv}")
    except FileExistsError:
        print(f"[CSV] Appending to existing file: {args.output_csv}")

    # Initialize instrument
    inst = None
    try:
        inst = Keithley2461(args.resource, mock=args.mock, terminals=args.terminals)
        
        # Handle connection test mode
        if args.test_connection:
            success = inst.test_connection()
            sys.exit(0 if success else 1)

        # Main testing loop
        print("\n" + "=" * 60)
        print("BATTERY CELL TESTING READY")
        print("=" * 60)
        print("Scan a cell barcode or type serial number to begin.")
        print("Type 'q' or press Ctrl+C to quit.\n")
        
        while True:
            try:
                serial_number = input("Cell serial number: ").strip()
                
                if serial_number.lower() == 'q':
                    print("\nExiting...")
                    break
                    
                if not serial_number:
                    print("  (empty input - please scan barcode or type serial number)")
                    continue

                # Check for duplicate serial number in existing results
                existing_data = check_duplicate_serial(args.output_csv, serial_number)
                
                if existing_data is not None:
                    action = prompt_duplicate_action(serial_number, existing_data)
                    
                    if action == 'skip':
                        print("\n[SKIP] Test cancelled. Enter a new serial number.\n")
                        continue
                    elif action == 'rename':
                        # Prompt for a new serial number instead
                        new_serial = input("\nEnter the correct serial number: ").strip()
                        if not new_serial or new_serial.lower() == 'q':
                            print("\n[SKIP] Test cancelled.\n")
                            continue
                        serial_number = new_serial
                        
                        # Check if the new serial is also a duplicate
                        existing_data = check_duplicate_serial(args.output_csv, serial_number)
                        if existing_data is not None:
                            print(f"\n[WARNING] '{serial_number}' also exists in the file!")
                            action = prompt_duplicate_action(serial_number, existing_data)
                            if action == 'skip' or action == 'rename':
                                print("\n[SKIP] Test cancelled. Please start over.\n")
                                continue
                            # action == 'retest' falls through to remove and test
                            
                    if action == 'retest' or (action == 'rename' and existing_data):
                        # Remove the old entry before retesting
                        remove_serial_from_csv(args.output_csv, serial_number, fieldnames)

                # Run test sequence
                results = run_tests(inst, serial_number)
                
                # Append results to CSV
                with open(args.output_csv, 'a', newline='') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writerow(results)
                
                print(f"[CSV] Results saved for {serial_number}")
                inst.beep_success()
                
            except KeyboardInterrupt:
                print("\n\nInterrupted by user. Exiting...")
                break
            except Exception as e:
                print(f"\n[ERROR] Test failed for cell: {e}")
                print("        Check connections and try again.\n")

    except pyvisa.errors.VisaIOError as e:
        print(f"\n[ERROR] Failed to connect to instrument: {e}")
        print("\nTroubleshooting steps:")
        print("  1. Verify USB cable is connected")
        print("  2. Check instrument is powered on")
        print("  3. Verify RESOURCE_NAME constant matches your instrument")
        print("  4. Run: python -c \"import pyvisa; print(pyvisa.ResourceManager('@py').list_resources())\"")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        sys.exit(1)
    finally:
        if inst is not None:
            inst.close()


if __name__ == "__main__":
    main()
