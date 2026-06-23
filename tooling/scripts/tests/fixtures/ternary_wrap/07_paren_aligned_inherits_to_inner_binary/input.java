public class Demo
{
    public String describe(boolean flag, String name, int count, String status)
    {
        return ((flag) ? "name=[ " + name + " ], count=[ " + count + " ], status=[ " + status + " ]" : "no data");
    }
}
