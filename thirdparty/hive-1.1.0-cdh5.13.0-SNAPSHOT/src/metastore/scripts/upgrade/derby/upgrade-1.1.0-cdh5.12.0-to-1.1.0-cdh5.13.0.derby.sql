-- Upgrade MetaStore schema from 1.1.0-cdh5.12.0 to 1.1.0-cdh5.13.0

UPDATE "APP".VERSION SET SCHEMA_VERSION='1.1.0', SCHEMA_VERSION_V2='1.1.0-cdh5.13.0', VERSION_COMMENT='Hive release version 1.1.0-cdh5.13.0' where VER_ID=1;
