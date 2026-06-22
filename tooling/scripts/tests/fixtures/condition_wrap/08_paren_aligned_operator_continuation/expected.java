public class Demo
{
    public boolean shouldProcess(boolean ignoreEnvironment,
                                 java.util.Map<String, String> result,
                                 String key)
    {
        return (ignoreEnvironment
                || (result.containsKey(key)
                    && (!Boolean.FALSE.equals(result.get(key)))));
    }
}
