public class Demo
{
    public void run()
    {
        ignoreEnvironment = (ignoreEnvironment
            || (result.containsKey(ignoreEnvOption)
                && (!Boolean.FALSE.equals(
                    result.get(ignoreEnvOption).getProcessedValue()))));
    }
}
