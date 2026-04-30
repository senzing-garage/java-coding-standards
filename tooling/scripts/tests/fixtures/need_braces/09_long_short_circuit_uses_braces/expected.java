public class Foo
{
    public void method()
    {
        if (somethingExtremelyLongConditionThatGoesOnAndOnAndOnAndOn) {
            throw new IllegalStateException("a long-ish message here");
        }
    }
}
