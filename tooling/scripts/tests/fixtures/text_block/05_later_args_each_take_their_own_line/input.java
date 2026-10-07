public class Demo
{
    public void run(SomeService service, String userId)
    {
        service.executeQuery("""
            SELECT *
            FROM users
            """,
            userId,
            IsolationLevel.READ_COMMITTED);
    }
}
