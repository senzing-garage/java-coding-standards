public class Foo
{
    public void method()
    {
        try (Connection conn = openConnection();
             Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery("SELECT 1")) {
            consume(rs);
        }
    }
}
