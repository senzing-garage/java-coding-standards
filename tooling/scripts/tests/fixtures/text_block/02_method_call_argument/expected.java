public class Demo
{
    public void run(SomeService service)
    {
        service.executeQuery("""
            SELECT *
            FROM users
            WHERE id = ?
            """);
    }
}
