public class Demo
{
    public void run(Duration durationValue)
    {
        if (durationValue == null
            || durationValue.isZero() || this.environment.isDestroyed())
        {
            return;
        }
    }
}
