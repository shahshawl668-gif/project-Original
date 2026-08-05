// Provision the application user for the payroll database.
//
// Collections and indexes are NOT created here — the API creates them on
// startup (`init_indexes()` in app/database.py), which keeps index definitions
// in one place, versioned with the code that depends on them.

const dbName = process.env.MONGO_INITDB_DATABASE || 'payroll';
const appUser = process.env.MONGO_APP_USER || 'payroll_app';
const appPassword = process.env.MONGO_APP_PASSWORD || 'payroll_app';

db = db.getSiblingDB(dbName);

const existing = db.getUser(appUser);
if (!existing) {
  db.createUser({
    user: appUser,
    pwd: appPassword,
    roles: [{ role: 'readWrite', db: dbName }],
  });
  print(`created application user '${appUser}' on '${dbName}'`);
} else {
  print(`application user '${appUser}' already exists on '${dbName}'`);
}
