import argparse
import csv
import time
import sys
import string
import pyvisa

RESOURCE_NAME = "USBn::0x5E6::0x2461::04628946::INSTR"

required_packages = {
    'pyvisa': 'pyvisa',
    'serial': 'pyserial'
}
missing_packages = []
for import_name, install_name in required_packages.items():
    try:
        __import__(import_name)
    except ImportError:
        missing_packages.append(install_name)

if missing_packages:
    print("\n\033[91mError: Missing required dependencies.\033[0m")
    print(f"The following packages are missing: {', '.join(missing_packages)}")
    sys.exit(1)

# Configurable parameters
kChargeComplianceLimit_volts = 4.2
kDischargeCompianceLimit_volts = 2.5
kR0PulseCurrent_amps = 7 # TODO: Need 10 here, but will exceed 2461 current limit for DC?
kR0PulseDuration_seconds = 0.0025
kDcirCurrent_amps = 3.0
kDcirDuration_seconds = 10.0
kVoltageSenseDwell_seconds = 0.1

class Keithley2461:
    def __init__(self, resource_name, mock=False, terminals='front'):
        self.mock = mock
        if not self.mock:
            # Create a resource manager using pyvisa-py backend
            rm = pyvisa.ResourceManager('@py')
            # Open connection to the Keithley 2461
            self.inst = rm.open_resource(RESOURCE_NAME)
            # Configure communication settings (common for USB instruments)
            self.inst.timeout = 5000  # 5 second timeout
            self.inst.write_termination = '\n'
            self.inst.read_termination = '\n'
            
            # Reset to default state and clear status
            self.inst.write("*RST")
            self.inst.write("*CLS")
            
            # Configure 4-wire remote sense mode
            self.inst.write(":SENS:VOLT:RSEN ON")
            
            # Select terminals
            if terminals.lower() == 'rear':
                self.inst.write(":ROUTe:TERMinals REAR")
            else:
                self.inst.write(":ROUTe:TERMinals FRONT")
            
            # Set source function to current mode
            self.inst.write(":SOURce:FUNCtion CURRent")
            
            # Set source current range to auto
            self.inst.write(":SOURce:CURR:RANGe:AUTO ON")
            
            # Set voltage measurement range to auto
            self.inst.write(":SENS:VOLT:RANGe:AUTO ON")
            
            # Set current measurement range to auto
            self.inst.write(":SENS:CURR:RANGe:AUTO ON")
            
            # Turn output ON (required for 4-wire measurements)
            self.inst.write(":OUTPut:STATe ON")
        else:
            print(f"Mocking connection to {resource_name}")

    @staticmethod
    def CleanString(inputString):
        return "".join(filter(lambda x: x in string.printable, inputString))

    @staticmethod
    def ParseReading(inputString):
        cleanedString = Keithley2461.CleanString(inputString)
        splitString = cleanedString.split(',')
        dataDict = {'voltage': float(splitString[0]), \
                    'current': float(splitString[1]), \
                    'resistance': float(splitString[2]), \
                    'time': float(splitString[3]), \
                    'status': float(splitString[4])}
        return dataDict

    def close(self):
        if not self.mock:
            self.inst.write(":OUTP OFF")
            self.inst.close()

    def output_on(self):
        if not self.mock:
            self.inst.write(":OUTP ON")

    def output_off(self):
        if not self.mock:
            self.inst.write(":OUTP OFF")
    
    def beep_success(self):
        if not self.mock:
            self.inst.write("SYST:BEEP:IMM 1400, 0.1")
            time.sleep(0.1)
            self.inst.write("SYST:BEEP:IMM 2000, 0.05")
            time.sleep(0.05)

    def measure_voltage(self):
        if self.mock: return 3.7

        self.inst.write(":SENS:FUNC \"VOLT\"")
        voltage_reading = self.inst.query(":READ?")
        voltage_value = float(voltage_reading.strip())
        print(f"   Voltage: {voltage_value:.6f} V")
        return voltage_value

    def measure_current(self):
        if self.mock: return 0.0
        self.inst.write(":SOUR:FUNC:SHAP DC")
        return self.ParseReading(self.inst.query(":MEAS:CURR?"))['current']

    def source_current(self, current, voltage_limit):
        """Sets the source to current mode with a voltage compliance limit."""
        if not self.mock:
            self.inst.write("SENS:FUNC 'VOLT'")
            self.inst.write(":SOUR:FUNC CURR")
            self.inst.write(f":SOUR:CURR:LEV {current}")
            self.inst.write(f":SOUR:CURR:VLIM {voltage_limit}")

    def source_voltage(self, voltage, current_limit):
        """Sets the source to voltage mode with a current compliance limit."""
        if not self.mock:
            self.inst.write(":SOUR:FUNC:SHAP DC")
            self.inst.write(":SOUR:FUNC VOLT")
            self.inst.write(f":SOUR:VOLT {voltage}")
            self.inst.write(f":SENS:CURR:PROT {current_limit}")

    def source_pulse_current(self, current, voltage_limit, width, delay=0):
        """Executes a current pulse and returns the measured voltage."""
        if self.mock:
            return 3.8 if current > 0 else 3.6 # Mock voltage rise/drop
        
        # Configure current source mode with voltage measurement
        self.inst.write(":SOUR:FUNC CURR")
        self.inst.write(":SENS:FUNC \"VOLT\"")
        self.inst.write(":SENS:VOLT:RANG 20")
        
        # Set current range to support the requested current
        abs_current = abs(current)
        if abs_current > 7.0:
            self.inst.write(":SOUR:CURR:RANG 10")  # 10A pulse range
        else:
            self.inst.write(":SOUR:CURR:RANG:AUTO ON")
        
        # Set current level and voltage limit
        self.inst.write(f":SOUR:CURR {current}")
        self.inst.write(f":SOUR:CURR:VLIM {voltage_limit}")
        
        # Optional delay before pulse
        if delay > 0:
            time.sleep(delay)
        
        # Execute pulse: Turn on, wait for pulse width, measure, turn off
        self.inst.write(":OUTP ON")
        time.sleep(width)  # Wait for pulse duration
        voltage_reading = self.inst.query(":READ?")
        voltage_value = float(voltage_reading.strip())
        self.inst.write(":OUTP OFF")
        
        # Return to 0A
        self.inst.write(":SOUR:CURR 0")
        
        print(f"   Pulse voltage: {voltage_value:.4f} V")
        return voltage_value

    def test_connection(self):
        """Tests the connection to the instrument by querying its ID."""
        if self.mock:
            print("Mock connection successful.")
            return True
        
        try:
            idn = self.inst.query("*IDN?")
            self.beep_success()
            print(f"Connection successful. Instrument ID: {idn.strip()}")
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

def run_tests(inst, serial_number):
    print(f"Testing cell {serial_number}...")
    
    # 1. Open Circuit Voltage
    print("  Measuring OCV...")
    inst.source_current(0.0, kChargeComplianceLimit_volts)
    inst.output_on()
    time.sleep(kVoltageSenseDwell_seconds)
    ocv = inst.measure_voltage()
    inst.output_off()
    print(f"  OCV: {ocv:.4f} V")

    # 2. R0 Estimate
    print("  Measuring R0...")
    # Measure idle voltage for charge
    inst.output_on()
    v_idle_charge = inst.measure_voltage()
    inst.output_off()
    
    # Charge Pulse
    print(f"  Pulsing {kR0PulseCurrent_amps}A for {kR0PulseDuration_seconds}s...")
    v_load_charge = inst.source_pulse_current(kR0PulseCurrent_amps, kChargeComplianceLimit_volts, kR0PulseDuration_seconds)
    
    # Measure idle voltage for discharge
    print("  Measuring OCV...")
    inst.output_on()
    v_idle_discharge = inst.measure_voltage()
    inst.output_off()

    # Discharge Pulse
    print(f"  Pulsing {-kR0PulseCurrent_amps}A for {kR0PulseDuration_seconds}s...")
    v_load_discharge = inst.source_pulse_current(-kR0PulseCurrent_amps, kDischargeCompianceLimit_volts, kR0PulseDuration_seconds)

    r_charge = (v_load_charge - v_idle_charge) / kR0PulseCurrent_amps
    r_discharge = (v_idle_discharge - v_load_discharge) / kR0PulseCurrent_amps # Delta V / Delta I. Delta I is positive magnitude here.
    r0 = (r_charge + r_discharge) / 2.0
    print(f"  R0: {r0:.4f} Ohm")

    # # 3. DCIR Test
    # print("  Measuring DCIR...")
    # # Measure idle voltage for charge
    # v_idle_charge_dcir = inst.measure_voltage()
    
    # # Charge
    # print(f"  Sourcing {kDcirCurrent_amps}A for {kDcirDuration_seconds} seconds...")
    # inst.source_current(kDcirCurrent_amps, kChargeComplianceLimit_volts)
    # inst.output_on()
    # time.sleep(kDcirDuration_seconds)
    # v_load_charge_dcir = inst.measure_voltage()
    # inst.output_off()

    # # Measure idle voltage for discharge
    # v_idle_discharge_dcir = inst.measure_voltage()

    # # Discharge
    # print(f"  Sourcing {-kDcirCurrent_amps}A for {kDcirDuration_seconds} seconds...")
    # inst.source_current(-kDcirCurrent_amps, kDischargeCompianceLimit_volts)
    # inst.output_on()
    # time.sleep(kDcirDuration_seconds)
    # v_load_discharge_dcir = inst.measure_voltage()
    # inst.output_off()

    # r_charge_dcir = (v_load_charge_dcir - v_idle_charge_dcir) / kDcirCurrent_amps
    # r_discharge_dcir = (v_idle_discharge_dcir - v_load_discharge_dcir) / kDcirCurrent_amps
    # dcir = (r_charge_dcir + r_discharge_dcir) / 2.0
    # print(f"  DCIR: {dcir:.4f} Ohm")

    # results = {
    #     "Serial Number": serial_number,
    #     "OCV (V)": ocv,
    #     "R0 (Ohm)": r0,
    #     "R0 Charge (Ohm)": r_charge,
    #     "R0 Discharge (Ohm)": r_discharge,
    #     "DCIR (Ohm)": dcir,
    #     "DCIR Charge (Ohm)": r_charge_dcir,
    #     "DCIR Discharge (Ohm)": r_discharge_dcir
    # }
    
    results = {
        "Serial Number": serial_number,
        "OCV (V)": ocv,
        "R0 (Ohm)": 0,
        "R0 Charge (Ohm)": 0,
        "R0 Discharge (Ohm)": 0,
        "DCIR (Ohm)": 0,
        "DCIR Charge (Ohm)": 0,
        "DCIR Discharge (Ohm)": 0
    }
    
    return results

def main():
    parser = argparse.ArgumentParser(description="Battery Cell Testing Script")
    parser.add_argument("output_csv", help="Path to the output CSV file")
    parser.add_argument("--resource", default="GPIB0::24::INSTR", help="VISA resource string for Keithley 2430")
    parser.add_argument("--mock", action="store_true", help="Run in mock mode without hardware")
    parser.add_argument("--terminals", choices=['front', 'rear'], default='front', help="Select front or rear terminals (default: front)")
    parser.add_argument("--test-connection", action="store_true", help="Test connection to the instrument and exit")
    args = parser.parse_args()

    # Initialize CSV
    # Initialize CSV
    fieldnames = ["Serial Number", "OCV (V)", "R0 (Ohm)", "R0 Charge (Ohm)", "R0 Discharge (Ohm)", "DCIR (Ohm)", "DCIR Charge (Ohm)", "DCIR Discharge (Ohm)"]
    
    # Check if file exists to decide whether to write header
    try:
        with open(args.output_csv, 'x', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
    except FileExistsError:
        pass # Append to existing file

    try:
        inst = Keithley2461(args.resource, mock=args.mock, terminals=args.terminals)
        
        if args.test_connection:
            success = inst.test_connection()
            sys.exit(0 if success else 1)

        while True:
            try:
                serial_number = input("Input serial number (or 'q' to quit): ").strip()
                if serial_number.lower() == 'q':
                    break
                if not serial_number:
                    continue

                results = run_tests(inst, serial_number)
                
                with open(args.output_csv, 'a', newline='') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writerow(results)
                
                print(f"Test complete for {serial_number}. Results saved.")
                inst.beep_success()
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error testing cell: {e}")

    except Exception as e:
        print(f"Failed to initialize instrument: {e}")
    finally:
        if 'inst' in locals():
            inst.close()

if __name__ == "__main__":
    main()
