public class Demo
{
    public void run(PageParams params, long newBound)
    {
        if (params != null) {
            params.setEntityIdBound(
                newBound < 0L ? null : String.valueOf(newBound));
        }
    }
}
