# SQLTools

User guide for my SQL tools. Simple wrapper for some DB functionality to make things easier for me in python.

## Functions

## Classes

### ConnectionManager

### Manager
This is the Connection Manager on steroids. It lets you manage SQL files in addition to database connections, and run those files on connected databases. This will probably get split out into multiple objects later for improved atomicity, but it gets the job done.

#### Getting started
You can initialize the object like so:

```
```

You do not need a config file, as it is only necessary for the pointers to the log file path and the directory with your sql files. If they don't exist, they'll just get created as necessary.

#### **Manager**.**
asdlfkas;dl

#### **Manager**.*connect(self, name: str, params: dict) -> psycopg2.extensions.connection*
asdlfkas;dl

Same as [ConnectionManager](#connectionmanager)

#### **Manager**.*scan(self, subdir: str | None = None) -> list[ConnectionManagerLogEntry]*
asdlfkas;dl
