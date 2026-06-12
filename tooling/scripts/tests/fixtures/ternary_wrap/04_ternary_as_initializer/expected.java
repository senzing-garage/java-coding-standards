public class Demo
{
    public void run()
    {
        String status = (currentStatusIndicator == null)
            ? defaultValueForStatus() : currentStatusIndicator.label();
    }
}
