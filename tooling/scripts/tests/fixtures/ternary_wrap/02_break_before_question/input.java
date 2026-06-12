public class Demo
{
    public String describe(int statusCode)
    {
        return (statusCode == STATUS_ACTIVE_AND_RESPONSIVE) ? "active and responsive" : "inactive";
    }
}
