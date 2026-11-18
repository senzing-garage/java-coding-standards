class T
{
    void m()
    {
        try (InputStream is
                 = cls.getResourceAsStream(POM_PROPERTIES_PATH_XYZ))
        {
            props.load(is);
        }
        try {
            File file = File.createTempFile("test-", ".txt");
            try (FileOutputStream fos = new FileOutputStream(file);
                 OutputStreamWriter osw = new OutputStreamWriter(fos, encoding))
            {
                osw.write("x");
            }
        } finally {
        }
        try {
            for (String tableName : tableNames) {
                try (java.sql.ResultSet triggers = stmt.executeQuery(
                    "SELECT tgname, pg_get_triggerdef(oid) as triggerdef "
                    + "FROM pg_trigger " + "WHERE tgrelid = '" + tableName
                    + "'::regclass " + "AND NOT tgisinternal"))
                {
                    x();
                }
            }
        } finally {
        }
    }
}
