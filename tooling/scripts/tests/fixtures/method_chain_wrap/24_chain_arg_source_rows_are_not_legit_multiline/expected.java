public class Demo
{
    void run()
        throws Exception
    {
        {
            boolean usePostgreSQL = Boolean.TRUE
                .toString()
                .equals(
                    System.getProperty("com.senzing.listener.test.postgresql"));
        }
    }
}
