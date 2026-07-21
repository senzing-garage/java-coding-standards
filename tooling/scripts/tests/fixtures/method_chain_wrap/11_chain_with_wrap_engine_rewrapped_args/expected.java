public class Demo
{
    public void runWithVeryLongMethodName()
    {
        String result = thisIsAReallyLongVariableName
            .method(longArgumentNameOne, longArgumentNameTwo,
            longArgumentNameThree)
            .chainMethodB()
            .chainMethodC()
            .toString();
    }
}
