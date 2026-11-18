class T
{
    void m()
    {
        try {
            for (String tableName : tableNames) {
                try (java.sql.ResultSet triggers = stmt.executeQuery(
                    "SELECT tgname, pg_get_triggerdef(oid) as triggerdef "
                        + "FROM pg_trigger " + "WHERE tgrelid = '"
                        + tableName + "'::regclass "
                        + "AND NOT tgisinternal")) {
                    x();
                }
            }
        } finally {
        }
    }
}
