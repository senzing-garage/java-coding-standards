public class Demo
{
    java.sql.ResultSet cached;

    void run(java.sql.Connection conn) throws Exception
    {
        java.sql.ResultSet tablesXX = conn.getMetaData().getTables(null, "public", "%", new String[] { "T" });
        this.someVeryLongTargetNm = conn.getMetaData().getTables(null, "public", "%", new String[] { "T" });
    }
}
