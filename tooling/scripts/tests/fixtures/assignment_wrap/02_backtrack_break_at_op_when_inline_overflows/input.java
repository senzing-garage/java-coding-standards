public class Demo
{
    public void run()
    {
        String[] args = null;
        try
        {
            for (int i = 0; i < 10; i++)
            {
                args = new String[] { "--port", "9080", "--interface", "localhost" };
            }
        }
        catch (Exception e)
        {
        }
    }
}
