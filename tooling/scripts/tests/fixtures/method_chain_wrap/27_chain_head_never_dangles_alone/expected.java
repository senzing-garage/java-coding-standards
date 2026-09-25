public class Demo
{
    void run(java.sql.Connection conn)
        throws Exception
    {
        java.sql.ResultSet tables
            = conn.getMetaData()
                  .getTables(null, "public", "%", new String[] { "TABLE" });
    }
}
