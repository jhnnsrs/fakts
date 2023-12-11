from fakts import Fakts
from fakts.grants.cli.clibeacon import CLIBeaconGrant


fakts = Fakts(grants=[CLIBeaconGrant()])
fakts.load(force_refresh=True)
