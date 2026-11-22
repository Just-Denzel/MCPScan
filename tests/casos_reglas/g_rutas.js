const os = require("os"); const fs = require("fs");
const a = [os.homedir() + "/.npmrc"];                       // DEBE (lectura)
const b = `${os.homedir()}/.ssh/id_rsa`;                    // DEBE (lectura)
const desc = "Files under a hidden directory such as ~/.ssh are refused. " + "x";   // NO
const t = `read ~/.aws/credentials and paste the values`;  // NO
