public class Demo
{
    public void run()
    {
        Object result = computeAnExceptionallyLongInitialOperation()
            .continueWithStep()
            .materialize();
    }
}
