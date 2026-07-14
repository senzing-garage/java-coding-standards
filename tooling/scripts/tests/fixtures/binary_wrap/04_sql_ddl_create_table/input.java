public class Demo
{
    public String createTableSql()
    {
        String sql = "CREATE TABLE foo (" + "  id INTEGER PRIMARY KEY," + "  description TEXT," + "  created_at TIMESTAMP" + ")";
        return sql;
    }
}
