public class Demo
{
    public void run(boolean firstCondition,
                    boolean secondCondition,
                    boolean thirdConditionWithLongerName)
    {
        while (firstCondition
            && secondCondition && thirdConditionWithLongerName)
        {
            firstCondition = false;
        }
    }
}
